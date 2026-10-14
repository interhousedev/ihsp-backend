#!/usr/bin/env bash
# Build the backend image for a version and architecture and push it to GHCR.
#
# Usage: scripts/image_push.sh <version> [--arch amd64|arm64|all] [--owner OWNER] [--latest] [--load]
#   <version>    the image tag, e.g. 1.2.0 (also the VERSION label); use the same version for
#                iht-web's scripts/image_push.sh, then deploy with
#                scripts/cloud_deploy.sh <ssh-host> --tag <version>
#   --arch       amd64 (default, x86 servers), arm64, or all (both in one manifest)
#   --owner      the GHCR namespace (default: interhousedev, or IMAGE_OWNER from the environment)
#   --latest     also move the `latest` tag to this build
#   --load       build one architecture into the local Docker instead of pushing
#
# The image is ghcr.io/<owner>/ihsp-backend:<version>, plus :sha-<commit> when the working tree
# is clean. Needs `docker login ghcr.io` with a token that may write packages.
set -euo pipefail
cd "$(dirname "$0")/.."

version=
arch=amd64
owner=${IMAGE_OWNER:-interhousedev}
latest=0
load=0
while [ $# -gt 0 ]; do
    case "$1" in
        --arch) arch=${2:?--arch needs a value}; shift 2 ;;
        --owner) owner=${2:?--owner needs a value}; shift 2 ;;
        --latest) latest=1; shift ;;
        --load) load=1; shift ;;
        -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
        -*) echo "unknown argument: $1" >&2; exit 2 ;;
        *) version=$1; shift ;;
    esac
done
[ -n "$version" ] || { echo "usage: scripts/image_push.sh <version> [--arch amd64|arm64|all] [--owner OWNER] [--latest] [--load]" >&2; exit 2; }
case "$version" in *[!A-Za-z0-9._-]*) echo "invalid version: $version" >&2; exit 2 ;; esac
case "$arch" in
    amd64 | arm64) platforms=linux/$arch ;;
    all) platforms=linux/amd64,linux/arm64 ;;
    *) echo "unknown --arch: $arch (amd64, arm64 or all)" >&2; exit 2 ;;
esac
if [ "$load" -eq 1 ] && [ "$arch" = all ]; then
    echo "--load builds one architecture; pick --arch amd64 or arm64" >&2
    exit 2
fi

image=ghcr.io/$owner/ihsp-backend
revision=$(git rev-parse HEAD)
tags=(-t "$image:$version")
if [ -z "$(git status --porcelain)" ]; then
    tags+=(-t "$image:sha-$revision")
else
    echo "warning: uncommitted changes are in the build; no sha-<commit> tag" >&2
fi
[ "$latest" -eq 1 ] && tags+=(-t "$image:latest")

# A docker-container builder can build other architectures and push multi-platform manifests.
builder=ihsp
docker buildx inspect "$builder" > /dev/null 2>&1 || docker buildx create --name "$builder" --driver docker-container > /dev/null

output=--push
[ "$load" -eq 1 ] && output=--load

echo "==> $image:$version ($platforms) from $revision"
docker buildx build --builder "$builder" --platform "$platforms" \
    --build-arg VERSION="$version" \
    --build-arg REVISION="$revision" \
    --build-arg SOURCE="https://github.com/$owner/iht-backend" \
    "${tags[@]}" "$output" .

if [ "$load" -eq 0 ]; then
    docker buildx imagetools inspect "$image:$version" | sed -n '1,3p'
    echo "==> pushed $image:$version"
fi
