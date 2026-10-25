# Answers the container healthcheck on any host name.
location = /health {
    access_log off;
    default_type text/plain;
    return 200 "ok\n";
}
