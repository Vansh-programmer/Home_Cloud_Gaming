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
	leaseMu        sync.Mutex
	accountMu      sync.Mutex
	rateMu         sync.Mutex
	lease          *playerLease
	leaseLoaded    bool
	accounts       map[string]localAccount
	accountsLoaded bool
	rateLimits     = make(map[string]rateLimitBucket)
	httpClient     = &http.Client{Timeout: 5 * time.Second}
	validSessionID = regexp.MustCompile(`^[A-Za-z0-9_-]{16,128}$`)
	validUsername  = regexp.MustCompile(`^[a-zA-Z0-9_-]{3,32}$`)
	validAccountID = regexp.MustCompile(`^[a-f0-9]{64}$`)
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
	createAuthSession(w, account)
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
	createAuthSession(w, account)
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

func createAuthSession(w http.ResponseWriter, account localAccount) {
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
		HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode,
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
	if claims != nil {
		leaseMu.Lock()
		if loadLeaseLocked() == nil && lease != nil && lease.AccountID == accountID(claims.AccountID) && leaseIsActive() {
			lease = nil
			_ = persistLeaseLocked()
		}
		leaseMu.Unlock()
	}
	for _, name := range []string{"ryoku_auth", "ryoku_session"} {
		http.SetCookie(w, &http.Cookie{Name: name, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode})
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
	setSessionCookie(w, cookieValue(r))
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
			if account.ID == activeAccountID {
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
	defer leaseMu.Unlock()
	if err := loadLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if lease == nil || !leaseIsActive() {
		lease = nil
		if err := persistLeaseLocked(); err != nil {
			http.Error(w, "could not end player session", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusNoContent)
		return
	}
	previousLease := lease
	lease = nil
	if err := persistLeaseLocked(); err != nil {
		lease = previousLease
		http.Error(w, "could not end player session", http.StatusServiceUnavailable)
		return
	}
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
		if lease.AccountID != accountID || lease.SessionID != sessionID {
			w.Header().Set("Retry-After", "20")
			writeJSON(w, http.StatusConflict, map[string]string{"error": "another player is using the game server"})
			return
		}
	} else {
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
	setSessionCookie(w, body.SessionID)
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
	setSessionCookie(w, cookieValue(r))
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
	leaseMu.Lock()
	defer leaseMu.Unlock()
	if err := loadLeaseLocked(); err != nil {
		http.Error(w, "player session state unavailable", http.StatusServiceUnavailable)
		return
	}
	if leaseMatchesRequest(r, claims) {
		lease = nil
		if err := persistLeaseLocked(); err != nil {
			http.Error(w, "could not save player session state", http.StatusServiceUnavailable)
			return
		}
	}
	http.SetCookie(w, &http.Cookie{Name: "ryoku_session", Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode})
	w.WriteHeader(http.StatusNoContent)
}

func sameOriginRequest(r *http.Request) bool {
	expected := strings.TrimRight(strings.TrimSpace(os.Getenv("RYOKU_SITE_ORIGIN")), "/")
	if expected == "" {
		expected = "https://play.vanshdev.online"
	}
	return strings.TrimRight(r.Header.Get("Origin"), "/") == expected
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
	if accountsLoaded {
		return nil
	}
	accounts = make(map[string]localAccount)
	content, err := os.ReadFile(accountDatabasePath())
	if errors.Is(err, os.ErrNotExist) {
		accountsLoaded = true
		return nil
	}
	if err != nil {
		return err
	}
	var stored []localAccount
	if err := json.Unmarshal(content, &stored); err != nil {
		return err
	}
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
		if _, exists := accounts[username]; exists {
			return errors.New("duplicate local account database entry")
		}
		account.Username = username
		accounts[username] = account
	}
	accountsLoaded = true
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
	return os.Rename(temporary, path)
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
	for _, candidate := range []string{
		r.Header.Get("CF-Connecting-IP"),
		lastForwardedIP(r.Header.Get("X-Forwarded-For")),
	} {
		if address, err := netip.ParseAddr(strings.TrimSpace(candidate)); err == nil {
			return address.Unmap().String()
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

func lastForwardedIP(value string) string {
	parts := strings.Split(value, ",")
	if len(parts) == 0 {
		return ""
	}
	return strings.TrimSpace(parts[len(parts)-1])
}

func updateWolfAppHome(profileHome string) error {
	clientID := strings.TrimSpace(os.Getenv("WOLF_WEB_CLIENT_ID"))
	if !regexp.MustCompile(`^[0-9]+$`).MatchString(clientID) {
		return errors.New("WOLF_WEB_CLIENT_ID must be a numeric Wolf client id")
	}
	socketPath := strings.TrimSpace(os.Getenv("WOLF_SOCKET_PATH"))
	if socketPath == "" {
		socketPath = "/run/user/wolf/wolf.sock"
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "unix", socketPath)
	}}
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
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
		"Test ball",
	} {
		appPath := filepath.Join(basePath, profileHome, appTitle)
		if err := os.MkdirAll(appPath, 0777); err != nil {
			return err
		}
		if err := os.Chmod(appPath, 0777); err != nil {
			return err
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

func setSessionCookie(w http.ResponseWriter, value string) {
	if value == "" {
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:     "ryoku_session",
		Value:    value,
		Path:     "/",
		MaxAge:   int(leaseDuration.Seconds()),
		HttpOnly: true,
		Secure:   true,
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

func authSessionPath(token string) string {
	base := strings.TrimSpace(os.Getenv("RYOKU_AUTH_SESSION_DIR"))
	if base == "" {
		base = "/var/lib/ryoku-access/auth-sessions"
	}
	return filepath.Join(base, digest(token)+".json")
}

func saveAuthSession(token string, session authSession) error {
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
	content, err := os.ReadFile(authSessionPath(token))
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
