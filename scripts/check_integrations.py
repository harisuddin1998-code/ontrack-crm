"""Check the three outside systems the CRM depends on, and say which are down.

The GPS sync, the SJ_MIS database sync and the email sender all reach out to
something that is not this application. All three are written to log a
failure and carry on, which is right for a scheduled job - one unreachable
host must not take the CRM down with it - but it means a broken integration
looks exactly like a working one from the outside. This is the script that
tells them apart.

    python scripts/check_integrations.py            # check all three
    python scripts/check_integrations.py --gps      # just one
    python scripts/check_integrations.py --smtp --send-to you@example.com

Exit code is 0 when everything checked is healthy and 1 when anything is not,
so it can gate a deploy or run from cron.

Nothing here writes to the database, and no password is ever printed - a
configured secret is reported as its length and nothing more. No email is
sent unless --send-to names a recipient.
"""
import argparse
import json
import smtplib
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_config  # noqa: E402

PASS, FAIL, WARN = '[ OK ]', '[FAIL]', '[WARN]'


def secret(value):
    """Describe a secret without disclosing it."""
    if not value:
        return 'EMPTY  <- nothing configured'
    return 'set ({} chars)'.format(len(value))


def head(title):
    print()
    print(title)
    print('-' * len(title))


# ----------------------------------------------------------------------
# GPS
# ----------------------------------------------------------------------

def check_gps(config) -> bool:
    head('GPS API')
    url = (config.GPS_API_URL or '').strip()
    key = (config.GPS_API_KEY or '').strip()

    print('  GPS_API_URL   = {}'.format(url or 'EMPTY  <- nothing configured'))
    print('  GPS_API_KEY   = {}'.format(secret(key)))

    if not url:
        print(FAIL + ' GPS_API_URL is not set.')
        print('       The service builds "?api=user&ver=1.0&key=..." with no host in')
        print('       front of it, urllib rejects it as an unknown url type, and the')
        print('       error is swallowed - the sync reports 0 locations and looks calm.')
        print('       Fix: set GPS_API_URL and GPS_API_KEY in .env, then restart.')
        return False

    if not key:
        print(WARN + ' GPS_API_KEY is empty - the API will almost certainly refuse.')

    full = '{}?api=user&ver=1.0&key={}&cmd=OBJECT_GET_LOCATIONS%2C%2A'.format(url, key)
    try:
        req = urllib.request.Request(full, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        print(FAIL + ' HTTP {} from the GPS host: {}'.format(e.code, e.reason))
        return False
    except urllib.error.URLError as e:
        print(FAIL + ' Could not reach the GPS host: {}'.format(e.reason))
        print('       Check the host is up and that this server may reach it')
        print('       (firewall, VPN, and the port named in GPS_API_URL).')
        return False
    except ValueError as e:
        print(FAIL + ' GPS_API_URL is malformed: {}'.format(e))
        print('       It needs a scheme, e.g. http://host:8080/api/api.php')
        return False
    except Exception as e:                                        # noqa: BLE001
        print(FAIL + ' {}: {}'.format(type(e).__name__, e))
        return False

    if not body.strip():
        print(FAIL + ' The GPS API returned an empty body.')
        return False

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(FAIL + ' The GPS API returned something that is not JSON.')
        print('       First 200 characters: {!r}'.format(body[:200]))
        print('       A login or error page here usually means a bad or expired key.')
        return False

    if not isinstance(data, dict):
        print(FAIL + ' Expected a JSON object of devices, got {}.'.format(type(data).__name__))
        return False

    print(PASS + ' {} device location(s) returned.'.format(len(data)))
    return True


# ----------------------------------------------------------------------
# SJ_MIS (SQL Server)
# ----------------------------------------------------------------------

def check_internal_db(config) -> bool:
    head('Internal database (SJ_MIS / SQL Server)')
    print('  INTERNAL_DB_SERVER   = {}'.format(config.INTERNAL_DB_SERVER or 'EMPTY'))
    print('  INTERNAL_DB_NAME     = {}'.format(config.INTERNAL_DB_NAME or 'EMPTY'))
    print('  INTERNAL_DB_USER     = {}'.format(config.INTERNAL_DB_USER or 'EMPTY'))
    print('  INTERNAL_DB_PASSWORD = {}'.format(secret(config.INTERNAL_DB_PASSWORD)))
    print('  INTERNAL_DB_DRIVER   = {}'.format(config.INTERNAL_DB_DRIVER or 'EMPTY'))

    try:
        import pyodbc
    except ImportError:
        print(FAIL + ' pyodbc is not installed in this environment.')
        return False

    installed = list(pyodbc.drivers())
    print('  ODBC drivers on this machine: {}'.format(installed or 'NONE'))

    sql_drivers = [d for d in installed if 'SQL Server' in d]
    if not sql_drivers:
        print(FAIL + ' No SQL Server ODBC driver is installed.')
        print('       unixodbc on its own is only the driver manager; the Microsoft')
        print('       driver is a separate package. On Debian/Ubuntu install')
        print('       msodbcsql17 from the Microsoft apt repository (ACCEPT_EULA=Y).')
        print('       Without it every connection attempt fails and the non-reporting')
        print('       sync silently falls back to four built-in placeholder vehicles.')
        return False

    if not config.INTERNAL_DB_SERVER:
        print(FAIL + ' INTERNAL_DB_SERVER is not set.')
        return False

    # The configured driver first, then whatever else is installed.
    candidates = []
    if config.INTERNAL_DB_DRIVER:
        candidates.append(config.INTERNAL_DB_DRIVER.strip('{}'))
    candidates += [d for d in sql_drivers if d not in candidates]

    for driver in candidates:
        conn_str = (
            'DRIVER={' + driver + '};'
            'SERVER=' + str(config.INTERNAL_DB_SERVER) + ';'
            'DATABASE=' + str(config.INTERNAL_DB_NAME) + ';'
            'UID=' + str(config.INTERNAL_DB_USER) + ';'
            'PWD=' + str(config.INTERNAL_DB_PASSWORD)
        )
        try:
            conn = pyodbc.connect(conn_str, timeout=config.INTERNAL_DB_TIMEOUT)
        except Exception as e:                                    # noqa: BLE001
            print('  ...{}: {}'.format(driver, str(e)[:150]))
            continue

        try:
            cursor = conn.cursor()
            cursor.execute('SELECT @@VERSION')
            row = cursor.fetchone()
            version = str(row[0]).splitlines()[0] if row else ''
            print(PASS + ' Connected with "{}".'.format(driver))
            print('       {}'.format(version[:110]))
            return True
        finally:
            conn.close()

    print(FAIL + ' Every driver was tried and none could connect.')
    print('       Until this is fixed the non-reporting sync inserts four fabricated')
    print('       vehicles (LEB-2021-9981, ICT-2023-4510, KHI-2022-8871, PEW-2020-3321)')
    print('       into the live list and reports success.')
    return False


# ----------------------------------------------------------------------
# SMTP
# ----------------------------------------------------------------------

def check_smtp(config, send_to=None) -> bool:
    head('Email (SMTP)')
    server = config.MAIL_SERVER
    port = config.MAIL_PORT
    print('  MAIL_SERVER    = {}:{}'.format(server, port))
    print('  MAIL_USE_TLS   = {}'.format(config.MAIL_USE_TLS))
    print('  MAIL_USE_SSL   = {}'.format(config.MAIL_USE_SSL))
    print('  MAIL_USERNAME  = {}'.format(config.MAIL_USERNAME or 'EMPTY'))
    print('  MAIL_PASSWORD  = {}'.format(secret(config.MAIL_PASSWORD)))
    print('  DEFAULT_SENDER = {}'.format(config.MAIL_DEFAULT_SENDER or 'EMPTY'))

    if not config.MAIL_PASSWORD:
        print(WARN + ' MAIL_PASSWORD is empty. If the server wants authentication then')
        print('       every send fails and send_email only returns False - completion')
        print('       notices and the month-end pack go nowhere, quietly.')

    try:
        if config.MAIL_USE_SSL:
            smtp = smtplib.SMTP_SSL(server, port, timeout=20)
        else:
            smtp = smtplib.SMTP(server, port, timeout=20)
    except socket.timeout:
        print(FAIL + ' Timed out connecting to {}:{}.'.format(server, port))
        print('       Outbound SMTP on this port is often blocked by the host.')
        return False
    except OSError as e:
        print(FAIL + ' Could not connect to {}:{} - {}'.format(server, port, e))
        return False

    healthy = True
    try:
        smtp.ehlo()
        if config.MAIL_USE_TLS and not config.MAIL_USE_SSL:
            smtp.starttls()
            smtp.ehlo()
        print(PASS + ' Connected to {}:{}.'.format(server, port))

        if config.MAIL_USERNAME and config.MAIL_PASSWORD:
            try:
                smtp.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
                print(PASS + ' Authenticated as {}.'.format(config.MAIL_USERNAME))
            except smtplib.SMTPAuthenticationError as e:
                print(FAIL + ' Authentication refused: {} {!r}'.format(e.smtp_code, e.smtp_error))
                return False
        else:
            print(WARN + ' Skipping login - username or password is missing.')
            healthy = False

        if send_to:
            msg = ('From: ' + str(config.MAIL_DEFAULT_SENDER) + '\r\n'
                   'To: ' + send_to + '\r\n'
                   'Subject: On Track CRM - integration check\r\n\r\n'
                   'If you are reading this, SMTP works from the CRM server.\r\n')
            smtp.sendmail(config.MAIL_DEFAULT_SENDER, [send_to], msg)
            print(PASS + ' Test message accepted for delivery to {}.'.format(send_to))
    finally:
        try:
            smtp.quit()
        except Exception:                                         # noqa: BLE001
            pass

    return healthy


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gps', action='store_true', help='check the GPS API only')
    parser.add_argument('--db', action='store_true', help='check the SJ_MIS database only')
    parser.add_argument('--smtp', action='store_true', help='check email only')
    parser.add_argument('--send-to', metavar='ADDRESS',
                        help='actually send a test email to this address')
    args = parser.parse_args()

    everything = not (args.gps or args.db or args.smtp)
    config = get_config()

    print('On Track CRM - integration check')
    print('Config in use: {}'.format(config.__class__.__name__))

    results = {}
    if everything or args.gps:
        results['GPS API'] = check_gps(config)
    if everything or args.db:
        results['Internal database'] = check_internal_db(config)
    if everything or args.smtp:
        results['Email'] = check_smtp(config, args.send_to)

    head('Summary')
    for name, good in results.items():
        print('  {} {}'.format(PASS if good else FAIL, name))

    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
