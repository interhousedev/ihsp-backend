# Response headers of the server-rendered pages of the api process: short links and file
# links (s.), room pages (/r/), book pages, feeds and robots.txt (lib.). The pages carry an
# inline <style>, cover images from the object store and plain same-origin forms (PIN,
# report), nothing else. See headers-api.inc for why HSTS is repeated here.
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
