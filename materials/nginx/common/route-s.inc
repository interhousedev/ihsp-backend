# s.<domain>: the static share viewer under /ai/; short links and file links are served by
# the api process by Host routing (install_short_link_host) at the root of this host.
location ^~ /ai/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-html.inc;
    proxy_pass $up_api;
}
