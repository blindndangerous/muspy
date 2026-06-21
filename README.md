# muspy

[muspy](https://muspy.com) is an album release notification service.

## Modernization

This fork is planning a modern rebuild of Muspy. The existing Python 2/Django
1.3 code is preserved for provenance and reference only.

Start with:

- `docs/superpowers/specs/2026-06-21-muspy-modernization-design.md`
- `docs/agent-handoff.md`

## Development

To set up development environment you need to install nginx and virtualenv, then run:

    % virtualenv env
    % source env/bin/activate
    % pip install -r requirements.txt

Edit your main `nginx.conf`:

    http {
        ...
        include /path/to/muspy/nginx-dev.conf;
    }

Update the project location in `muspy/nginx-dev.conf` and restart nginx.

Add this line to your `/etc/hosts`:

    127.0.0.1  muspy.dev

Go to the project directory and run `make db` to create an empty database.

Type `make run` and go to <http://muspy.dev/>. If static files don't load make
sure nginx has rx permissions for the `muspy/static` directory.
