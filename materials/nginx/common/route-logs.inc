# logs.<domain>: Bugsink (error tracking). The UI and the Sentry-protocol ingest share the host:
# browsers and backend processes send events to https://logs.<domain>/api/<project>/envelope/
# (the DSN carries the public project key). Everything else is the Bugsink UI, which requires
# a login. Bugsink sends its own security headers, so the edge adds none here.
location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_bugsink;
}
