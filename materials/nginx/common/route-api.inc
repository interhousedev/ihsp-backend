# api.<domain>: identity, bot and api processes Regex locations are tried in order: the first match wins.
# Every location adds the JSON response headers (headers-api.inc). The login and OAuth paths
# and the Telegram webhook are rate-limited per client address (zones: default.conf.template).

# The EMIS gateway is for the worker and scheduler on the Docker network only.
location ^~ /internal/ {
    return 404;
}

# Composition endpoint that lives in the api process although it sits under /admin/teachers.
location ~ ^/v1/admin/teachers/[^/]+/profile$ {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    proxy_pass $up_api;
}

location ~ ^/v1/(id|oauth)/ {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    limit_req zone=ihsp_auth burst=20 nodelay;
    proxy_pass $up_identity;
}

location ~ ^/v1/admin/(users|teachers|audit)(/|$) {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    proxy_pass $up_identity;
}

# Telegram webhook (path secret and secret_token are checked by the bot process). The
# secret is part of the path, so these requests are kept out of the access log.
location ^~ /telegram/ {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    limit_req zone=ihsp_auth burst=50 nodelay;
    access_log off;
    proxy_pass $up_bot;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    proxy_pass $up_api;
}
