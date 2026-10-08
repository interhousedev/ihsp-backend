# api.<domain>: identity, bot and api processes (backend/PLAN.md § Processes and hosts,
# FINAL_PLAN § 2.1). Regex locations are tried in order: the first match wins.

# The EMIS gateway is for the worker and scheduler on the Docker network only.
location ^~ /internal/ {
    return 404;
}

# Composition endpoint that lives in the api process although it sits under /admin/teachers.
location ~ ^/v1/admin/teachers/[^/]+/profile$ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}

location ~ ^/v1/(id|oauth)/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_identity;
}

location ~ ^/v1/admin/(users|teachers|audit)(/|$) {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_identity;
}

# Telegram webhook (path secret and secret_token are checked by the bot process).
location ^~ /telegram/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_bot;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}
