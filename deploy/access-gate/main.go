package main

import (
	"context"
	"crypto/hmac"
	cryptorand "crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	leaseDuration  = 2 * time.Minute
	authDuration   = 7 * 24 * time.Hour
	passwordRounds = 310000
)

type playerIdentity struct {
	AccountID string
	Username  string
	Role      string
}

type localAccount struct {
	ID           string `json:"id"`
	Username     string `json:"username"`
	Salt         string `json:"salt"`
	PasswordHash string `json:"password_hash"`
	Role         string `json:"role"`
	CreatedAt    int64  `json:"created_at"`
}

type playerLease struct {
	AccountID   string `json:"account_id"`
	SessionID   string `json:"session_id"`
	ProfileHome string `json:"profile_home"`
	ExpiresAt   int64  `json:"expires_at"`
}

type sessionRequest struct {
	SessionID string `json:"session_id"`
}

type accountCredentials struct {
	Username    string `json:"username"`
	NewUsername string `json:"new_username,omitempty"`
	Password    string `json:"password"`
}

type authSession struct {
	AccountID string `json:"account_id"`
	Username  string `json:"username"`
	Role      string `json:"role"`
	ExpiresAt int64  `json:"expires_at"`
}

type adminAccount struct {
	ID        string `json:"id"`
	Username  string `json:"username"`
	Role      string `json:"role"`
	CreatedAt int64  `json:"created_at"`
}

type rateLimitBucket struct {
	StartedAt time.Time
	Requests  int
}

var (
	leaseMu         sync.Mutex
	accountMu       sync.Mutex
	rateMu          sync.Mutex
	lease           *playerLease
	leaseLoaded     bool
	accounts        map[string]localAccount
	accountsLoaded  bool
	accountsModTime time.Time
	accountsSize    int64
	rateLimits      = make(map[string]rateLimitBucket)
	httpClient      = &http.Client{Timeout: 5 * time.Second}
	validSessionID  = regexp.MustCompile(`^[A-Za-z0-9_-]{16,128}$`)
	validUsername   = regexp.MustCompile(`^[a-zA-Z0-9_-]{3,32}$`)
	validAccountID  = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

func main() {
	if len(os.Args) > 1 {
		if err := createAccountCommand(os.Args[1]); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	http.HandleFunc("/verify", verifyHandler)
	http.HandleFunc("/verify-stream", verifyStreamHandler)
	http.HandleFunc("/auth/register", registerHandler)
	http.HandleFunc("/auth/login", loginHandler)
	http.HandleFunc("/auth/logout", logoutHandler)
	http.HandleFunc("/identity", identityHandler)
	http.HandleFunc("/admin/accounts", adminAccountsHandler)
	http.HandleFunc("/admin/session", adminSessionHandler)
	http.HandleFunc("/admin/session/end", adminEndSessionHandler)
	http.HandleFunc("/moonlight-authenticate", moonlightAuthenticateHandler)
	http.HandleFunc("/session/acquire", acquireHandler)
	http.HandleFunc("/session/heartbeat", heartbeatHandler)
	http.HandleFunc("/session/release", releaseHandler)
	http.HandleFunc("/status", statusHandler)
	http.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	if err := http.ListenAndServe("127.0.0.1:9080", nil); err != nil {
		fmt.Fprintln(os.Stderr, "access-gate stopped:", err)
		os.Exit(1)
	}
}

func registerHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	if !allowRequest(r, "register", 5, time.Hour) {
		http.Error(w, "too many registration attempts; try again later", http.StatusTooManyRequests)
		return
	}
	credentials, ok := decodeCredentials(w, r)
	if !ok {
		return
	}
	username := strings.ToLower(strings.TrimSpace(credentials.Username))
	if !validUsername.MatchString(username) || len(credentials.Password) < 12 || len(credentials.Password) > 128 {
		http.Error(w, "use a 3-32 character username and a password of at least 12 characters", http.StatusBadRequest)
		return
	}
	salt := make([]byte, 16)
	if _, err := cryptorand.Read(salt); err != nil {
		http.Error(w, "could not create account", http.StatusInternalServerError)
		return
	}
	accountIDBytes := make([]byte, 32)
	if _, err := cryptorand.Read(accountIDBytes); err != nil {
		http.Error(w, "could not create account", http.StatusInternalServerError)
		return
	}
	account := localAccount{
		ID:           hex.EncodeToString(accountIDBytes),
		Username:     username,
		Salt:         base64.RawURLEncoding.EncodeToString(salt),
		PasswordHash: base64.RawURLEncoding.EncodeToString(passwordKey(credentials.Password, salt)),
		Role:         "player",
		CreatedAt:    time.Now().Unix(),
	}
	accountMu.Lock()
	if err := loadAccountsLocked(); err != nil {
		accountMu.Unlock()
		http.Error(w, "account storage is unavailable", http.StatusServiceUnavailable)
		return
	}
	if _, exists := accounts[username]; exists {
		accountMu.Unlock()
		http.Error(w, "that username is already in use", http.StatusConflict)
		return
	}
	accounts[username] = account
	if err := persistAccountsLocked(); err != nil {
		delete(accounts, username)
		accountMu.Unlock()
		http.Error(w, "could not save account", http.StatusServiceUnavailable)
		return
	}
	accountMu.Unlock()
	createAuthSession(w, r, account)
}

// createAccountCommand provisions an account offline from JSON on stdin. It is
// used inside the access-gate container so an admin role is never self-service.
func createAccountCommand(command string) error {
	if command == "set-password" {
		return setAccountPasswordCommand()
	}

	role := ""
	switch command {
	case "create-admin":
		role = "admin"
	case "create-player":
		role = "player"
	default:
		return errors.New("supported commands: create-admin, create-player, set-password")
	}
	var credentials accountCredentials
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 4096)).Decode(&credentials); err != nil {
		return errors.New("provide username and password as JSON on stdin")
	}
	username := strings.ToLower(strings.TrimSpace(credentials.Username))
	if !validUsername.MatchString(username) || len(credentials.Password) < 12 || len(credentials.Password) > 128 {
		return errors.New("use a 3-32 character username and a password of 12-128 characters")
	}
	salt := make([]byte, 16)
	id := make([]byte, 32)
	if _, err := cryptorand.Read(salt); err != nil {
		return errors.New("could not create account salt")
	}
	if _, err := cryptorand.Read(id); err != nil {
		return errors.New("could not create account id")
	}
	account := localAccount{
		ID: hex.EncodeToString(id), Username: username,
		Salt:         base64.RawURLEncoding.EncodeToString(salt),
		PasswordHash: base64.RawURLEncoding.EncodeToString(passwordKey(credentials.Password, salt)),
		Role:         role, CreatedAt: time.Now().Unix(),
	}
	accountMu.Lock()
	defer accountMu.Unlock()
	if err := loadAccountsLocked(); err != nil {
		return fmt.Errorf("account storage unavailable: %w", err)
	}
	if _, exists := accounts[username]; exists {
		return errors.New("that username is already in use")
	}
	accounts[username] = account
	if err := persistAccountsLocked(); err != nil {
		delete(accounts, username)
		return fmt.Errorf("could not save account: %w", err)
	}
	_, err := fmt.Fprintf(os.Stdout, "%s %s\n", account.Username, account.ID)
	return err
}

// setAccountPasswordCommand replaces an existing account's password while
// preserving its ID, role, username, and creation time.
func setAccountPasswordCommand() error {
	var credentials accountCredentials
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 4096)).Decode(&credentials); err != nil {
		return errors.New("provide username and password as JSON on stdin")
	}
	username := strings.ToLower(strings.TrimSpace(credentials.Username))
	newUsername := strings.ToLower(strings.TrimSpace(credentials.NewUsername))
	if newUsername == "" {
		newUsername = username
	}
	if !validUsername.MatchString(username) || !validUsername.MatchString(newUsername) || len(credentials.Password) < 12 || len(credentials.Password) > 128 {
		return errors.New("use a 3-32 character username and a password of 12-128 characters")
	}
	salt := make([]byte, 16)
	if _, err := cryptorand.Read(salt); err != nil {
		return errors.New("could not create account salt")
	}

	accountMu.Lock()
	defer accountMu.Unlock()
	if err := loadAccountsLocked(); err != nil {
		return fmt.Errorf("account storage unavailable: %w", err)
	}
	account, exists := accounts[username]
	if !exists {
		return errors.New("account does not exist")
	}
	if newUsername != username {
		if _, exists := accounts[newUsername]; exists {
			return errors.New("the new username is already in use")
		}
	}
	previous := account
	account.Username = newUsername
	account.Salt = base64.RawURLEncoding.EncodeToString(salt)
	account.PasswordHash = base64.RawURLEncoding.EncodeToString(passwordKey(credentials.Password, salt))
	delete(accounts, username)
	accounts[newUsername] = account
	if err := persistAccountsLocked(); err != nil {
		delete(accounts, newUsername)
		accounts[username] = previous
		return fmt.Errorf("could not save account: %w", err)
	}
	revokeAccountAuthSessions(account.ID)
	_, err := fmt.Fprintf(os.Stdout, "Password updated for %s\n", account.Username)
	return err
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	if !allowRequest(r, "login", 10, 15*time.Minute) {
		http.Error(w, "too many login attempts; try again later", http.StatusTooManyRequests)
		return
	}
	credentials, ok := decodeCredentials(w, r)
	if !ok {
		return
	}
	username := strings.ToLower(strings.TrimSpace(credentials.Username))
	accountMu.Lock()
	if err := loadAccountsLocked(); err != nil {
		accountMu.Unlock()
		http.Error(w, "account storage is unavailable", http.StatusServiceUnavailable)
		return
	}
	account, exists := accounts[username]
	accountMu.Unlock()
	if !validUsername.MatchString(username) || !exists {
		burnPasswordCheck(credentials.Password)
		http.Error(w, "username or password is incorrect", http.StatusUnauthorized)
		return
	}
	salt, saltErr := base64.RawURLEncoding.DecodeString(account.Salt)
	expected, hashErr := base64.RawURLEncoding.DecodeString(account.PasswordHash)
	if saltErr != nil || hashErr != nil || !hmac.Equal(passwordKey(credentials.Password, salt), expected) {
		http.Error(w, "username or password is incorrect", http.StatusUnauthorized)
		return
	}
	createAuthSession(w, r, account)
}

func decodeCredentials(w http.ResponseWriter, r *http.Request) (accountCredentials, bool) {
	var credentials accountCredentials
	if err := json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&credentials); err != nil {
		http.Error(w, "enter a username and password", http.StatusBadRequest)
		return credentials, false
	}
	if len(credentials.Password) > 128 {
		http.Error(w, "password is too long", http.StatusBadRequest)
		return credentials, false
	}
	return credentials, true
}

func createAuthSession(w http.ResponseWriter, r *http.Request, account localAccount) {
	token, err := randomToken(32)
	if err != nil {
		http.Error(w, "could not create sign-in session", http.StatusInternalServerError)
		return
	}
	session := authSession{AccountID: account.ID, Username: account.Username, Role: account.Role, ExpiresAt: time.Now().Add(authDuration).Unix()}
	if err := saveAuthSession(token, session); err != nil {
		http.Error(w, "could not save sign-in session", http.StatusServiceUnavailable)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: "ryoku_auth", Value: token, Path: "/", MaxAge: int(authDuration.Seconds()),
		HttpOnly: true, Secure: cookieSecure(r), SameSite: http.SameSiteStrictMode,
	})
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]string{"username": account.Username, "role": account.Role})
}

func logoutHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	claims, _ := authenticatedClaims(r)
	if token := authCookieValue(r); token != "" {
		if err := os.Remove(authSessionPath(token)); err != nil && !errors.Is(err, os.ErrNotExist) {
			http.Error(w, "could not end the sign-in session", http.StatusServiceUnavailable)
			return
		}
	}
	stoppedLease := false
	if claims != nil {
		leaseMu.Lock()
		if loadLeaseLocked() == nil && lease != nil && lease.AccountID == accountID(claims.AccountID) && leaseIsActive() {
			lease = nil
			_ = persistLeaseLocked()
			stoppedLease = true
		}
		leaseMu.Unlock()
	}
	if stoppedLease {
		stopWolfClientSession()
	}
	secure := cookieSecure(r)
	for _, name := range []string{"ryoku_auth", "ryoku_session"} {
		http.SetCookie(w, &http.Cookie{Name: name, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: secure, SameSite: http.SameSiteStrictMode})
	}
	w.WriteHeader(http.StatusNoContent)
}

func moonlightAuthenticateHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	leaseMu.Lock()
	if err := loadLeaseLocked(); err != nil {
		leaseMu.Unlock()
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if !leaseMatchesRequest(r, claims) {
		leaseMu.Unlock()
		http.Error(w, "start a player session before continuing", http.StatusLocked)
		return
	}
	leaseMu.Unlock()
	if !leaseMatchesRequestAfterUnlock(claims, cookieValue(r)) {
		http.Error(w, "player session expired", http.StatusLocked)
		return
	}
	settingsPath := strings.TrimSpace(os.Getenv("MOONLIGHT_SETTINGS_PATH"))
	if settingsPath == "" {
		settingsPath = "/run/moonlight/.local/share/MoonlightWeb/MoonlightWeb/settings.json"
	}
	settingsFile, err := os.Open(settingsPath)
	if err != nil {
		http.Error(w, "Moonlight authentication is unavailable", http.StatusServiceUnavailable)
		return
	}
	defer settingsFile.Close()
	var settings struct {
		CertificateToken string `json:"certificate_token"`
		CertificateAuth  bool   `json:"cert_auth_enabled"`
	}
	if err := json.NewDecoder(io.LimitReader(settingsFile, 1<<20)).Decode(&settings); err != nil || !settings.CertificateAuth || settings.CertificateToken == "" {
		http.Error(w, "Moonlight authentication is not configured", http.StatusServiceUnavailable)
		return
	}
	body, err := json.Marshal(map[string]any{
		"certificate":  settings.CertificateToken,
		"remember":     false,
		"machine_name": "Ryoku local player",
	})
	if err != nil {
		http.Error(w, "Moonlight authentication failed", http.StatusServiceUnavailable)
		return
	}
	request, err := http.NewRequestWithContext(r.Context(), http.MethodPost, "http://127.0.0.1:8080/api/auth/validate", strings.NewReader(string(body)))
	if err != nil {
		http.Error(w, "Moonlight authentication failed", http.StatusServiceUnavailable)
		return
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := httpClient.Do(request)
	if err != nil {
		http.Error(w, "Moonlight authentication service is unavailable", http.StatusServiceUnavailable)
		return
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, 64*1024))
	if err != nil {
		http.Error(w, "Moonlight authentication failed", http.StatusServiceUnavailable)
		return
	}
	for _, cookie := range response.Cookies() {
		http.SetCookie(w, cookie)
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(response.StatusCode)
	_, _ = w.Write(responseBody)
}

func leaseMatchesRequestAfterUnlock(claims *playerIdentity, rawSessionID string) bool {
	leaseMu.Lock()
	defer leaseMu.Unlock()
	if loadLeaseLocked() != nil || !leaseIsActive() || lease.AccountID != accountID(claims.AccountID) {
		return false
	}
	return lease.SessionID == digest(rawSessionID)
}

func verifyHandler(w http.ResponseWriter, r *http.Request) {
	if _, err := authenticatedClaims(r); err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	w.WriteHeader(http.StatusOK)
}

func verifyStreamHandler(w http.ResponseWriter, r *http.Request) {
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	leaseMu.Lock()
	defer leaseMu.Unlock()
	if err := loadLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if !leaseMatchesRequest(r, claims) {
		http.Error(w, "start a player session before streaming", http.StatusLocked)
		return
	}
	if err := renewLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	setSessionCookie(w, r, cookieValue(r))
	w.WriteHeader(http.StatusOK)
}

func identityHandler(w http.ResponseWriter, r *http.Request) {
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]string{"username": claims.Username, "role": claims.Role})
}

func adminAccountsHandler(w http.ResponseWriter, r *http.Request) {
	claims, err := authenticatedClaims(r)
	if err != nil || claims.Role != "admin" {
		http.Error(w, "admin access required", http.StatusForbidden)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	accountMu.Lock()
	defer accountMu.Unlock()
	if err := loadAccountsLocked(); err != nil {
		http.Error(w, "account storage is unavailable", http.StatusServiceUnavailable)
		return
	}
	result := make([]adminAccount, 0, len(accounts))
	for _, account := range accounts {
		result = append(result, adminAccount{ID: account.ID, Username: account.Username, Role: account.Role, CreatedAt: account.CreatedAt})
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{"accounts": result})
}

func adminSessionHandler(w http.ResponseWriter, r *http.Request) {
	claims, err := authenticatedClaims(r)
	if err != nil || claims.Role != "admin" {
		http.Error(w, "admin access required", http.StatusForbidden)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	leaseMu.Lock()
	if err := loadLeaseLocked(); err != nil {
		leaseMu.Unlock()
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if !leaseIsActive() {
		leaseMu.Unlock()
		w.Header().Set("Cache-Control", "no-store")
		writeJSON(w, http.StatusOK, map[string]any{"active": false})
		return
	}
	activeAccountID := lease.AccountID
	expiresAt := lease.ExpiresAt
	leaseMu.Unlock()

	username := "Unknown player"
	accountMu.Lock()
	if err := loadAccountsLocked(); err == nil {
		for _, account := range accounts {
			if account.ID == activeAccountID || accountID(account.ID) == activeAccountID {
				username = account.Username
				break
			}
		}
	}
	accountMu.Unlock()
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{"active": true, "username": username, "expires_at": expiresAt})
}

func adminEndSessionHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || !sameOriginRequest(r) {
		http.Error(w, "same-origin POST required", http.StatusForbidden)
		return
	}
	claims, err := authenticatedClaims(r)
	if err != nil || claims.Role != "admin" {
		http.Error(w, "admin access required", http.StatusForbidden)
		return
	}
	leaseMu.Lock()
	if err := loadLeaseLocked(); err != nil {
		leaseMu.Unlock()
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if lease == nil || !leaseIsActive() {
		lease = nil
		if err := persistLeaseLocked(); err != nil {
			leaseMu.Unlock()
			http.Error(w, "could not end player session", http.StatusServiceUnavailable)
			return
		}
		leaseMu.Unlock()
		stopWolfClientSession()
		w.WriteHeader(http.StatusNoContent)
		return
	}
	previousLease := lease
	lease = nil
	if err := persistLeaseLocked(); err != nil {
		lease = previousLease
		leaseMu.Unlock()
		http.Error(w, "could not end player session", http.StatusServiceUnavailable)
		return
	}
	leaseMu.Unlock()
	stopWolfClientSession()
	w.WriteHeader(http.StatusNoContent)
}

func acquireHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	var body sessionRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1024)).Decode(&body); err != nil || !validSessionID.MatchString(body.SessionID) {
		http.Error(w, "invalid player session id", http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(os.Getenv("WOLF_WEB_CLIENT_ID")) == "" {
		http.Error(w, "Wolf web client is not configured", http.StatusServiceUnavailable)
		return
	}

	accountID := accountID(claims.AccountID)
	sessionID := digest(body.SessionID)
	profileHome := "account-" + accountID
	leaseMu.Lock()
	defer leaseMu.Unlock()
	if err := loadLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if leaseIsActive() {
		if lease.AccountID != accountID {
			w.Header().Set("Retry-After", "20")
			writeJSON(w, http.StatusConflict, map[string]string{"error": "another player is using the game server"})
			return
		}
		lease.SessionID = sessionID
	} else {
		if lease != nil && lease.AccountID != accountID {
			stopWolfClientSession()
		}
		if err := prepareProfileHome(profileHome); err != nil {
			http.Error(w, "could not prepare the private player storage", http.StatusServiceUnavailable)
			return
		}
		if err := updateWolfAppHome(profileHome); err != nil {
			http.Error(w, "could not prepare the private player profile", http.StatusServiceUnavailable)
			return
		}
		lease = &playerLease{AccountID: accountID, SessionID: sessionID, ProfileHome: profileHome}
	}
	if err := renewLeaseLocked(); err != nil {
		http.Error(w, "could not save player session state", http.StatusServiceUnavailable)
		return
	}
	setSessionCookie(w, r, body.SessionID)
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]string{"username": claims.Username})
}

func heartbeatHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	leaseMu.Lock()
	defer leaseMu.Unlock()
	if err := loadLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if !leaseMatchesRequest(r, claims) {
		http.Error(w, "player session expired", http.StatusLocked)
		return
	}
	if err := renewLeaseLocked(); err != nil {
		http.Error(w, "could not save player session state", http.StatusServiceUnavailable)
		return
	}
	setSessionCookie(w, r, cookieValue(r))
	w.WriteHeader(http.StatusNoContent)
}

func releaseHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !sameOriginRequest(r) {
		http.Error(w, "same-origin request required", http.StatusForbidden)
		return
	}
	claims, err := authenticatedClaims(r)
	if err != nil {
		http.Error(w, "sign-in required", http.StatusUnauthorized)
		return
	}
	stoppedLease := false
	leaseMu.Lock()
	if err := loadLeaseLocked(); err != nil {
		leaseMu.Unlock()
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if leaseMatchesRequest(r, claims) {
		lease = nil
		if err := persistLeaseLocked(); err != nil {
			leaseMu.Unlock()
			http.Error(w, "could not save player session state", http.StatusServiceUnavailable)
			return
		}
		stoppedLease = true
	}
	leaseMu.Unlock()
	if stoppedLease {
		stopWolfClientSession()
	}
	http.SetCookie(w, &http.Cookie{Name: "ryoku_session", Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: cookieSecure(r), SameSite: http.SameSiteStrictMode})
	w.WriteHeader(http.StatusNoContent)
}

func statusHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	claims, _ := authenticatedClaims(r)
	leaseMu.Lock()
	_ = loadLeaseLocked()
	busy := leaseIsActive()
	you := false
	if busy && claims != nil && lease.AccountID == accountID(claims.AccountID) {
		you = true
	}
	leaseMu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":     true,
		"online": true,
		"busy":   busy,
		"you":    you,
	})
}

func sameOriginRequest(r *http.Request) bool {
	origin := strings.TrimRight(strings.TrimSpace(r.Header.Get("Origin")), "/")
	if origin == "" {
		return false
	}
	expected := strings.TrimRight(strings.TrimSpace(os.Getenv("RYOKU_SITE_ORIGIN")), "/")
	if expected == "" {
		expected = "https://play.vanshdev.online"
	}
	if origin == expected {
		return true
	}
	return origin == "http://localhost" || origin == "http://127.0.0.1"
}

func cookieSecure(r *http.Request) bool {
	origin := strings.TrimRight(strings.TrimSpace(r.Header.Get("Origin")), "/")
	if origin == "http://localhost" || origin == "http://127.0.0.1" {
		return false
	}
	host := strings.TrimSpace(r.Header.Get("X-Forwarded-Host"))
	if host == "" {
		host = strings.TrimSpace(r.Host)
	}
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	if (host == "localhost" || host == "127.0.0.1") && r.Header.Get("X-Forwarded-Proto") != "https" {
		return false
	}
	return true
}

func authenticatedClaims(r *http.Request) (*playerIdentity, error) {
	token := authCookieValue(r)
	if token == "" {
		return nil, errors.New("sign-in required")
	}
	session, err := loadAuthSession(token)
	if err != nil {
		return nil, err
	}
	return &playerIdentity{Username: session.Username, AccountID: session.AccountID, Role: session.Role}, nil
}

func accountDatabasePath() string {
	if path := strings.TrimSpace(os.Getenv("RYOKU_ACCOUNT_DB")); path != "" {
		return path
	}
	return "/var/lib/ryoku-access/accounts.json"
}

func loadAccountsLocked() error {
	path := accountDatabasePath()
	info, statErr := os.Stat(path)
	if errors.Is(statErr, os.ErrNotExist) {
		accounts = make(map[string]localAccount)
		accountsLoaded = true
		accountsModTime = time.Time{}
		accountsSize = 0
		return nil
	}
	if statErr != nil {
		return statErr
	}
	if accountsLoaded && info.ModTime().Equal(accountsModTime) && info.Size() == accountsSize {
		return nil
	}
	content, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var stored []localAccount
	if err := json.Unmarshal(content, &stored); err != nil {
		return err
	}
	loaded := make(map[string]localAccount, len(stored))
	for _, account := range stored {
		salt, saltErr := base64.RawURLEncoding.DecodeString(account.Salt)
		hash, hashErr := base64.RawURLEncoding.DecodeString(account.PasswordHash)
		if !validUsername.MatchString(account.Username) || !validAccountID.MatchString(account.ID) || saltErr != nil || len(salt) != 16 || hashErr != nil || len(hash) != sha256.Size {
			return errors.New("invalid local account database")
		}
		if account.Role == "" {
			account.Role = "player"
		}
		if account.Role != "admin" && account.Role != "player" {
			return errors.New("invalid local account role")
		}
		username := strings.ToLower(account.Username)
		if _, exists := loaded[username]; exists {
			return errors.New("duplicate local account database entry")
		}
		account.Username = username
		loaded[username] = account
	}
	accounts = loaded
	accountsLoaded = true
	accountsModTime = info.ModTime()
	accountsSize = info.Size()
	return nil
}

func persistAccountsLocked() error {
	path := accountDatabasePath()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	stored := make([]localAccount, 0, len(accounts))
	for _, account := range accounts {
		stored = append(stored, account)
	}
	content, err := json.Marshal(stored)
	if err != nil {
		return err
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, content, 0600); err != nil {
		return err
	}
	if err := os.Rename(temporary, path); err != nil {
		return err
	}
	if info, err := os.Stat(path); err == nil {
		accountsModTime = info.ModTime()
		accountsSize = info.Size()
	}
	return nil
}

func passwordKey(password string, salt []byte) []byte {
	mac := hmac.New(sha256.New, []byte(password))
	_, _ = mac.Write(append(salt, 0, 0, 0, 1))
	u := mac.Sum(nil)
	result := append([]byte(nil), u...)
	for round := 1; round < passwordRounds; round++ {
		mac = hmac.New(sha256.New, []byte(password))
		_, _ = mac.Write(u)
		u = mac.Sum(nil)
		for i := range result {
			result[i] ^= u[i]
		}
	}
	return result
}

func burnPasswordCheck(password string) {
	if len(password) > 128 {
		password = password[:128]
	}
	passwordKey(password, []byte("ryoku-invalid-account"))
}

func allowRequest(r *http.Request, purpose string, limit int, window time.Duration) bool {
	key := purpose + ":" + requestIP(r)
	now := time.Now()
	rateMu.Lock()
	defer rateMu.Unlock()
	bucket := rateLimits[key]
	if now.Sub(bucket.StartedAt) >= window {
		bucket = rateLimitBucket{StartedAt: now}
	}
	if bucket.Requests >= limit {
		rateLimits[key] = bucket
		return false
	}
	bucket.Requests++
	rateLimits[key] = bucket
	if len(rateLimits) > 10000 {
		for entry, old := range rateLimits {
			if now.Sub(old.StartedAt) > 24*time.Hour {
				delete(rateLimits, entry)
			}
		}
	}
	return true
}

func requestIP(r *http.Request) string {
	if cookieSecure(r) {
		if cfRay := strings.TrimSpace(r.Header.Get("CF-Ray")); cfRay != "" {
			if address, err := netip.ParseAddr(strings.TrimSpace(r.Header.Get("CF-Connecting-IP"))); err == nil {
				return address.Unmap().String()
			}
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		if address, parseErr := netip.ParseAddr(host); parseErr == nil {
			return address.Unmap().String()
		}
	}
	return "unknown"
}

func wolfUnixClient() (*http.Client, string, error) {
	clientID := strings.TrimSpace(os.Getenv("WOLF_WEB_CLIENT_ID"))
	if !regexp.MustCompile(`^[0-9]+$`).MatchString(clientID) {
		return nil, "", errors.New("WOLF_WEB_CLIENT_ID must be a numeric Wolf client id")
	}
	socketPath := strings.TrimSpace(os.Getenv("WOLF_SOCKET_PATH"))
	if socketPath == "" {
		socketPath = "/run/user/wolf/wolf.sock"
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "unix", socketPath)
	}}
	return &http.Client{Transport: transport, Timeout: 5 * time.Second}, clientID, nil
}

func stopWolfClientSession() {
	client, clientID, err := wolfUnixClient()
	if err != nil {
		return
	}
	listReq, err := http.NewRequest(http.MethodGet, "http://wolf/api/v1/sessions", nil)
	if err != nil {
		return
	}
	listResp, err := client.Do(listReq)
	if err != nil {
		return
	}
	listBody, _ := io.ReadAll(io.LimitReader(listResp.Body, 64*1024))
	_ = listResp.Body.Close()
	var sessionList struct {
		Sessions []struct {
			ClientID string `json:"client_id"`
		} `json:"sessions"`
	}
	if json.Unmarshal(listBody, &sessionList) != nil {
		return
	}
	found := false
	for _, s := range sessionList.Sessions {
		if s.ClientID == clientID {
			found = true
			break
		}
	}
	if !found {
		return
	}
	body, err := json.Marshal(map[string]string{"session_id": clientID})
	if err != nil {
		return
	}
	stopReq, err := http.NewRequest(http.MethodPost, "http://wolf/api/v1/sessions/stop", strings.NewReader(string(body)))
	if err != nil {
		return
	}
	stopReq.Header.Set("Content-Type", "application/json")
	stopResp, err := client.Do(stopReq)
	if err == nil {
		_ = stopResp.Body.Close()
	}
}

func updateWolfAppHome(profileHome string) error {
	client, clientID, err := wolfUnixClient()
	if err != nil {
		return err
	}
	body, err := json.Marshal(map[string]any{
		"client_id":        clientID,
		"app_state_folder": profileHome,
		"settings":         nil,
	})
	if err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodPost, "http://wolf/api/v1/clients/settings", strings.NewReader(string(body)))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("Wolf API unavailable: %w", err)
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, 64*1024))
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("Wolf API returned %d", response.StatusCode)
	}
	var result struct {
		Success bool `json:"success"`
	}
	if err := json.Unmarshal(responseBody, &result); err != nil || !result.Success {
		return errors.New("Wolf did not confirm the private app home update")
	}
	return nil
}

func prepareProfileHome(profileHome string) error {
	if !regexp.MustCompile(`^account-[a-f0-9]{64}$`).MatchString(profileHome) {
		return errors.New("invalid account storage folder")
	}
	basePath := strings.TrimSpace(os.Getenv("WOLF_APP_STATE_FOLDER"))
	if basePath == "" {
		basePath = "/var/lib/ryoku-user-storage"
	}
	for _, appTitle := range []string{
		"Steam Cloud Gaming",
		"Heroic Games Launcher (Epic & GOG)",
		"SuperTux",
		"Extreme Tux Racer",
		"Neverball",
		"Luanti Voxel Sandbox",
		"Endless Sky",
		"Chromium B.S.U.",
		"Test ball",
	} {
		appPath := filepath.Join(basePath, profileHome, appTitle)
		if err := os.MkdirAll(appPath, 0777); err != nil {
			return err
		}
		if err := os.Chmod(appPath, 0777); err != nil {
			return err
		}
		for _, relCache := range []string{
			".cache",
			".cache/nvidia",
			".cache/nvidia/GLCache",
			".cache/dxvk",
			".cache/mesa_shader_cache",
		} {
			cachePath := filepath.Join(appPath, relCache)
			if err := os.MkdirAll(cachePath, 0777); err != nil {
				return err
			}
			_ = os.Chmod(cachePath, 0777)
		}
	}
	return nil
}

func leaseMatchesRequest(r *http.Request, claims *playerIdentity) bool {
	if lease == nil || !leaseIsActive() || lease.AccountID != accountID(claims.AccountID) {
		return false
	}
	cookie, err := r.Cookie("ryoku_session")
	if err != nil || cookie.Value == "" {
		return false
	}
	return lease.SessionID == digest(cookie.Value)
}

func leaseIsActive() bool {
	return lease != nil && lease.ExpiresAt > time.Now().Unix()
}

func renewLeaseLocked() error {
	if lease == nil {
		return errors.New("no active player lease")
	}
	lease.ExpiresAt = time.Now().Add(leaseDuration).Unix()
	return persistLeaseLocked()
}

func loadLeaseLocked() error {
	if leaseLoaded {
		return nil
	}
	leaseLoaded = true
	statePath := leasePath()
	content, err := os.ReadFile(statePath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	var stored playerLease
	if err := json.Unmarshal(content, &stored); err != nil {
		return err
	}
	if stored.AccountID == "" || stored.SessionID == "" || stored.ProfileHome == "" {
		return errors.New("invalid stored player lease")
	}
	lease = &stored
	return nil
}

func persistLeaseLocked() error {
	statePath := leasePath()
	if err := os.MkdirAll(filepath.Dir(statePath), 0700); err != nil {
		return err
	}
	if lease == nil {
		if err := os.Remove(statePath); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		return nil
	}
	content, err := json.Marshal(lease)
	if err != nil {
		return err
	}
	tmpPath := statePath + ".tmp"
	if err := os.WriteFile(tmpPath, content, 0600); err != nil {
		return err
	}
	return os.Rename(tmpPath, statePath)
}

func leasePath() string {
	if path := strings.TrimSpace(os.Getenv("RYOKU_SESSION_STATE")); path != "" {
		return path
	}
	return "/var/lib/ryoku-access/session.json"
}

func setSessionCookie(w http.ResponseWriter, r *http.Request, value string) {
	if value == "" {
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:     "ryoku_session",
		Value:    value,
		Path:     "/",
		MaxAge:   int(leaseDuration.Seconds()),
		HttpOnly: true,
		Secure:   cookieSecure(r),
		SameSite: http.SameSiteStrictMode,
	})
}

func cookieValue(r *http.Request) string {
	cookie, err := r.Cookie("ryoku_session")
	if err != nil {
		return ""
	}
	return cookie.Value
}

func authCookieValue(r *http.Request) string {
	cookie, err := r.Cookie("ryoku_auth")
	if err != nil {
		return ""
	}
	return cookie.Value
}

func authSessionDir() string {
	base := strings.TrimSpace(os.Getenv("RYOKU_AUTH_SESSION_DIR"))
	if base == "" {
		base = "/var/lib/ryoku-access/auth-sessions"
	}
	return base
}

func authSessionPath(token string) string {
	return filepath.Join(authSessionDir(), digest(token)+".json")
}

func revokeAccountAuthSessions(targetAccountID string) {
	dir := authSessionDir()
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	now := time.Now().Unix()
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		fullPath := filepath.Join(dir, entry.Name())
		content, err := os.ReadFile(fullPath)
		if err != nil {
			continue
		}
		var s authSession
		if json.Unmarshal(content, &s) != nil || s.ExpiresAt <= now || (targetAccountID != "" && s.AccountID == targetAccountID) {
			_ = os.Remove(fullPath)
		}
	}
}

func saveAuthSession(token string, session authSession) error {
	revokeAccountAuthSessions("")
	path := authSessionPath(token)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	content, err := json.Marshal(session)
	if err != nil {
		return err
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, content, 0600); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

func loadAuthSession(token string) (*authSession, error) {
	if !regexp.MustCompile(`^[A-Za-z0-9_-]{40,64}$`).MatchString(token) {
		return nil, errors.New("invalid sign-in session")
	}
	path := authSessionPath(token)
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var session authSession
	if err := json.Unmarshal(content, &session); err != nil {
		return nil, err
	}
	if session.Role == "" {
		session.Role = "player"
	}
	if !validAccountID.MatchString(session.AccountID) || !validUsername.MatchString(session.Username) || (session.Role != "admin" && session.Role != "player") || session.ExpiresAt <= time.Now().Unix() {
		_ = os.Remove(path)
		return nil, errors.New("expired or invalid sign-in session")
	}
	return &session, nil
}

func randomToken(size int) (string, error) {
	buffer := make([]byte, size)
	if _, err := cryptorand.Read(buffer); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buffer), nil
}

func accountID(subject string) string {
	return digest(subject)
}

func digest(value string) string {
	valueHash := sha256.Sum256([]byte(value))
	return hex.EncodeToString(valueHash[:])
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
