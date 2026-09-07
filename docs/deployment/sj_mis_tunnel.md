# Reaching SJ_MIS from the deployed server

The SJ_MIS database lives at `192.168.99.97`, a private address on the office
LAN. The deployed container runs in a datacentre and cannot route to it, so
the non-reporting sync fails there on every run. That is not a configuration
mistake in the CRM - there is no value for `INTERNAL_DB_SERVER` that makes a
private address routable from the internet. A network path has to exist
first.

This describes the path we chose and why, and the three things that have to
line up before the sync works.

## Why a tunnel and not a port forward

Forwarding TCP 1433 on the office router would work in an afternoon and is
the wrong answer. It puts SQL Server on the public internet, where it is
found by scanners within hours, and the sync currently authenticates as `sa`
- a full administrator. A compromise there is not "the sync breaks", it is
the whole database.

A tunnel exposes the database to one machine instead of to everyone, and
costs nothing extra to run.

## Tailscale

Built on WireGuard. Keys are generated on each device and the private key
never leaves it, so traffic between the office node and the server is
end-to-end encrypted. Tailscale's coordination servers distribute public keys
and connection metadata; they cannot decrypt traffic, including when a
connection falls back to relaying through them.

Two things about that are worth being deliberate about rather than
discovering later.

**The coordination plane decides who is in your network.** It hands out the
public keys that peers trust, so a compromised control plane could in
principle introduce a node. Turning on *tailnet lock* removes that: new nodes
must be signed by nodes you already trust, and an unsigned one is refused
whatever the control plane says.

**A subnet route is as wide as you make it.** Advertising `192.168.99.0/24`
bridges the entire office network to a cloud machine. The CRM needs exactly
one host, so advertise exactly one.

### Setting it up

On a machine that stays on, on the office LAN, and can already reach the
database (check with `python scripts/check_integrations.py --db`):

    tailscale up --advertise-routes=192.168.99.97/32

On the deployed server:

    tailscale up --accept-routes

Then approve the route in the admin console under Machines -> the office node
-> Subnet routes. Nothing reaches the database until that approval, so a node
joining the tailnet does not silently gain access.

Restrict it further with an ACL, so the server may open the database port and
nothing else:

    {
      "acls": [
        {
          "action": "accept",
          "src":    ["tag:crm-server"],
          "dst":    ["192.168.99.97:1433"]
        }
      ]
    }

Tag the server (`tailscale up --advertise-tags=tag:crm-server`) rather than
naming it, so replacing the machine does not mean rewriting the policy.

### What this depends on

The office node must stay powered on and online. It is now part of the
production path: if it sleeps, the sync stops - and, since the sync reports
failures honestly, says so rather than inventing vehicles.

## The three things that must line up

Connectivity alone is not enough. All three of these are required, and each
fails differently:

1. **A route to the host.** Without it, every connection attempt times out.
2. **The ODBC driver in the image.** `unixodbc` is only the driver manager and
   ships no driver for SQL Server; without `msodbcsql17` the connection fails
   on a missing library however the network is configured. The Dockerfile
   installs it.
3. **`INTERNAL_DB_*` in the server's `.env`.** `docker-compose.yml` passes
   `${INTERNAL_DB_SERVER:-}` and the rest, which fall back to empty. A
   missing or misplaced `.env` therefore does not fail loudly - it leaves the
   values blank, and the sync reports that it could not reach anything.

Check all three at once from inside the container:

    docker compose exec web python scripts/check_integrations.py --db

It prints the drivers actually installed, attempts the connection, and shows
the real error rather than a swallowed one.

## Use a read-only login

The sync only ever runs SELECTs. It should not connect as `sa`.

    CREATE LOGIN on_track_sync WITH PASSWORD = '<generated>';
    USE SJ_MIS;
    CREATE USER on_track_sync FOR LOGIN on_track_sync;
    ALTER ROLE db_datareader ADD MEMBER on_track_sync;

Then set `INTERNAL_DB_USER` and `INTERNAL_DB_PASSWORD` to that login. If the
credentials ever leak, they read a database that is already read-only to the
CRM instead of granting administrative control of the server.
