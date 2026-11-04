# id.<domain>: Hydra's public endpoints, everything else is the static id app
# (login, consent and logout pages, security pages, Telegram mini app login).
# Hydra is rate-limited per client address (zones: default.conf.template). Clients register
# at api.<domain>/v1/oauth/mcp/register, never at Hydra's own endpoint (it is switched off).
location = /oauth2/register {
    return 404;
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
