# Local player accounts

Ryoku uses its own username and password accounts. Sign-up, password checks,
and sessions run on the host; Google, Cloudflare Access, email delivery, and
other identity providers are not required. There are no external auth keys to
configure.

Players can create an account on the portal. Usernames are 3-32 characters
using letters, numbers, `_`, or `-`. Passwords must contain at least 12
characters. The access gate stores a random salt and a PBKDF2-HMAC-SHA256
password hash in the `ryoku-access-state` volume. Passwords are not stored.
Login and registration attempts are rate-limited per client IP.

The account database and login sessions live in the same persistent volume.
Back up `ryoku-access-state` together with `ryoku-user-storage`; losing the
account database makes those local accounts unavailable. Each new account gets
a random stable ID that maps to its private Wolf app home, so changing a
username does not merge or expose another player's files.

Accounts have either the `player` or `admin` role. Public registration always
creates a player. Admin accounts are provisioned from inside the access-gate
container with the offline `create-admin` command; an admin can view usernames,
account IDs, roles, and creation dates in the portal's Local accounts panel.
Passwords and password hashes are never shown in that panel.

Local sign-up proves that the player knows the password they chose. It does
not verify ownership of an email address because this setup does not send
email. The portal does not ask for an email address.

## Access rules

The portal shell and health endpoint are public. Account APIs, game-session
leases, Moonlight signalling, and streams require a valid local session. One
browser player can hold the Wolf/Moonlight Web slot at a time. Sign out to
revoke the browser session; idle sessions expire after seven days, while a
game lease expires after two minutes without a heartbeat.

To close registration later, disable the `/api/auth/register` route in
`Caddyfile` and restart the gateway. Existing users can continue to sign in.
