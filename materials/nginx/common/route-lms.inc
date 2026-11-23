# lms.<domain>: the static LMS app from the web container, except the files of H5P packages.
# The api serves those (GET /v1/lms/h5p/<signed token>/<path>) on the LMS host itself, so the
# player's scripts, styles, fonts and media are same-origin and the page CSP ('self') covers them.
# The signed token in the path is the access; there is no cookie or bearer.
location ^~ /v1/lms/h5p/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_api;
}

# Author-uploaded HTML widgets (GET /v1/lms/html-widgets/<signed token>/<path>): same scheme as
# H5P. The api sets the sandbox CSP on every response; the cookies of the LMS host never reach
# the api from here and no cookie comes back.
location ^~ /v1/lms/html-widgets/ {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    proxy_hide_header Set-Cookie;
    proxy_pass $up_api;
}

include /etc/nginx/ihsp/route-static.inc;
