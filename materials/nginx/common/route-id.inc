# id.<domain>: Hydra's public endpoints, everything else is the static id app
# (login, consent and logout pages, security pages, Telegram mini app login).
location ~ ^/(oauth2/|\.well-known/|userinfo$) {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_hydra;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
