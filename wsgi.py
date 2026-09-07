# wsgi.py
"""
WSGI entry point - what gunicorn serves in production.

    gunicorn -c deployment/gunicorn.conf.py wsgi:app

`src.app` deliberately exposes only the `create_app` factory and no
module-level application. Every test, script and migration imports that
module, and building a whole application - opening the database, registering
blueprints, starting the background scheduler - as a side effect of importing
it would make all of them slower and none of them predictable.

So the application object lives here instead, in a module nothing imports
except the server that is about to serve it.
"""
from src.app import create_app

app = create_app()

if __name__ == '__main__':
    # A convenience for `python wsgi.py`; production runs it through gunicorn,
    # and `run.py` is the one to use for local development (it also serves the
    # socket.io endpoint).
    app.run(host='0.0.0.0', port=5000)
