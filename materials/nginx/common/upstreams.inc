# Upstreams as variables: nginx resolves them through Docker's DNS at request time, so it
# starts (and keeps serving the others) even while one backend container is down.
set $up_web      http://web:8080;
set $up_api      http://api:8000;
set $up_identity http://identity:8001;
set $up_bot      http://bot:8002;
set $up_hydra    http://hydra:4444;
set $up_s3       http://s3:9000;
set $up_bugsink  http://bugsink:8000;
