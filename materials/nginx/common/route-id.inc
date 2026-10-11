# id.<domain>: Hydra's public endpoints, everything else is the static id app
# (login, consent and logout pages, security pages, Telegram mini app login).
# Hydra is rate-limited per client address (zones: default.conf.template); Dynamic Client
# Registration (open to the internet, used by MCP clients) much more tightly.
location = /oauth2/register {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-api.inc;
    limit_req zone=ihsp_register burst=5 nodelay;
    proxy_pass $up_hydra;
}

location ~ ^/(oauth2/|\.well-known/|userinfo$) {
    include /etc/nginx/ihsp/proxy.inc;
    limit_req zone=ihsp_auth burst=20 nodelay;
    proxy_pass $up_hydra;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
