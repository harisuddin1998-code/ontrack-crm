# Reaching SJ_MIS from the deployed server

The SJ_MIS database lives at `192.168.99.97`, a private address on the office
LAN. The deployed container runs in a datacentre and cannot route to it, so
the non-reporting sync fails there on every run. That is not a configuration
mistake in the CRM - there is no value for `INTERNAL_DB_SERVER` that makes a
private address routable from the internet. A network path has to exist
first.

## The one thing that cannot be avoided

Something inside the office network has to run the tunnel. A private address
is not reachable from outside by definition, so traffic has to be accepted
and forwarded by a device that is already on that LAN. No hosted service
changes this.

What that device is, though, is a choice - and it does not have to be a
workstation. The database server is itself always on, so it can terminate the
tunnel directly. That is the arrangement described here: no intermediary
machine, no relay host, and nothing that has to be left switched on for the
sync to keep working beyond the database server itself.

## The link runs from the database server, outbound

WireGuard on `192.168.99.97`, dialling out to the deployed server. Two
properties matter:

**Outbound only.** The database server opens the connection; the office
firewall never accepts an inbound one. Nothing is forwarded on the router and
nothing about SQL Server is exposed to the internet. A scan of the office IP
finds no new open port, because there is not one.

**No third party.** The two machines hold each other's public keys and talk
directly. There is no coordination service that could introduce a peer, so
the trust boundary is the two hosts and nothing else. Tailscale is a
reasonable alternative and easier to operate, but its control plane decides
who is in the network; this does not have that property.

### On the deployed server

    apt-get install -y wireguard
    wg genkey | tee server.key | wg pubkey > server.pub

`/etc/wireguard/wg0.conf`:

    [Interface]
    Address    = 10.9.0.1/24
    ListenPort = 51820
    PrivateKey = <server.key>

    [Peer]
    # SJ_MIS database server
    PublicKey  = <sj_mis.pub>
    AllowedIPs = 10.9.0.2/32

Open UDP 51820 to the internet on this host only, and start it:

    systemctl enable --now wg-quick@wg0

### On the database server

Install the WireGuard Windows client, then use this tunnel config:

    [Interface]
    Address    = 10.9.0.2/32
    PrivateKey = <sj_mis.key>

    [Peer]
    PublicKey           = <server.pub>
    Endpoint            = 149.102.142.158:51820
    AllowedIPs          = 10.9.0.1/32
    PersistentKeepalive = 25

`AllowedIPs = 10.9.0.1/32` is deliberately narrow: it routes only the CRM
server over the tunnel. The database server's own traffic is untouched, and
the tunnel cannot become a general route into the office network.

`PersistentKeepalive` holds the mapping open through the office NAT so the
server can reach back without the database server having to speak first.

Set the tunnel to start automatically as a service, so a reboot does not
quietly end the sync.

### Then point the CRM at the tunnel address

In the server's `.env`:

    INTERNAL_DB_SERVER=10.9.0.2

Not `192.168.99.97`. The tunnel address is what the deployed server can
reach, and using it means the office LAN is never routed at all - only the
one host on the other end of the tunnel.

Allow 1433 from `10.9.0.1` in the database server's firewall, and confirm SQL
Server is listening on the tunnel interface as well as the LAN one.

## If you cannot install on the database server

Terminate the tunnel on the office router or firewall instead - MikroTik,
pfSense, OPNsense, UniFi, Fortinet and Sophos all do WireGuard or IPsec, and
the router is already always on. The shape is identical; only the device
holding the key changes. Restrict the tunnel to `192.168.99.97:1433` in the
firewall policy so it does not become a route to the whole LAN.

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

## Refreshing is already automatic

Nothing needs scheduling once the link is up. The application runs the
non-reporting sync every thirty minutes and re-dumps the SJ_MIS master
vehicle roster at 02:00 daily (`src/scheduler.py`). Until the link exists
both report failure and leave the stored data alone.

## Use a read-only login

The sync only ever runs SELECTs. It should not connect as `sa`.

    CREATE LOGIN on_track_sync WITH PASSWORD = '<generated>';
    USE SJ_MIS;
    CREATE USER on_track_sync FOR LOGIN on_track_sync;
    ALTER ROLE db_datareader ADD MEMBER on_track_sync;

Then set `INTERNAL_DB_USER` and `INTERNAL_DB_PASSWORD` to that login. If the
credentials ever leak, they read a database that is already read-only to the
CRM instead of granting administrative control of the server.
