#!/bin/sh
# Download the OpenCV face models into a directory (default /opt/face-models), verifying sha256.
set -eu
dir="${1:-/opt/face-models}"
mkdir -p "$dir"

fetch() {
    name="$1"; url="$2"; sum="$3"
    target="$dir/$name"
    if [ -f "$target" ] && [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$sum" ]; then
        return 0
    fi
    curl -fsSL "$url" -o "$target.tmp"
    if [ "$(sha256sum "$target.tmp" | cut -d' ' -f1)" != "$sum" ]; then
        rm -f "$target.tmp"
        echo "sha256 mismatch for $name" >&2
        exit 1
    fi
    mv "$target.tmp" "$target"
}

fetch face_detection_yunet_2023mar.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
fetch face_recognition_sface_2021dec.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
    0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
