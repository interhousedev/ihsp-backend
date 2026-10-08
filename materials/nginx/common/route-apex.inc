# <domain>/r/<slug>: classroom room pages (plain HTML from the api process).
location ^~ /r/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}
