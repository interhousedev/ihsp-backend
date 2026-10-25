# lms.<domain>: the static LMS app from the web container, except the files of H5P packages.
# The api serves those (GET /v1/lms/h5p/<signed token>/<path>) on the LMS host itself, so the
# player's scripts, styles, fonts and media are same-origin and the page CSP ('self') covers them.
# The signed token in the path is the access; there is no cookie or bearer.
location ^~ /v1/lms/h5p/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}

include /etc/nginx/ihsp/route-static.inc;
