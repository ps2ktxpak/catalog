# The scraper's container: the ps2ktxpak tools plus everything a pack goes through.
# Build from the repository root (wrangler does, see wrangler.jsonc):
#   docker build --platform linux/amd64 -f scraper/Dockerfile .
# Every tool is pinned, so a pack converted today and one converted next month went through the same code.

FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential clang cmake git ca-certificates meson ninja-build pkg-config \
      libglib2.0-dev libcurl4-openssl-dev libssl-dev libsodium-dev && rm -rf /var/lib/apt/lists/*

# megatools 1.12 (from git; the published builds predate Mega's newer shared folders)
ARG MEGATOOLS_COMMIT=a99821d
RUN git clone https://xff.cz/git/megatools /src/megatools && cd /src/megatools && git checkout $MEGATOOLS_COMMIT \
 && meson setup build -Dman=false --prefix=/opt/megatools && ninja -C build install

# kram, the encoder the inherited packs were converted with
ARG KRAM_COMMIT=97c56df
RUN git clone https://github.com/bmdhacks/kram /src/kram && cd /src/kram && git checkout $KRAM_COMMIT \
 && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --target kram -j"$(nproc)" \
 && install -D "$(find build -type f -name kram -perm -u+x | head -1)" /opt/kram/kram

# validate_ktx, against the app's own KTX parser
ARG ARMSX2_COMMIT=cdd19c58742a4cf97243dc88d8501d0138c8f613
RUN git clone --filter=blob:none --no-checkout https://github.com/ARMSX2/ARMSX2 /src/armsx2 && cd /src/armsx2 \
 && git sparse-checkout set --no-cone "/pcsx2/GS/*.h" /pcsx2/GS/Renderers/Common/ /pcsx2/GS/Renderers/HW/ /common/ /3rdparty/fmt/ && git checkout $ARMSX2_COMMIT
COPY scraper/validate_ktx.cpp /src/validate_ktx.cpp
RUN g++ -std=c++20 -O2 -msse4.1 -I/src/armsx2/pcsx2 -I/src/armsx2 -I/src/armsx2/common/include \
      -I/src/armsx2/3rdparty/fmt/include -DFMT_HEADER_ONLY /src/validate_ktx.cpp -o /opt/validate_ktx

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-yaml python3-jsonschema python3-openpyxl \
      ca-certificates curl git tar zstd xz-utils unzip libglib2.0-0t64 libcurl4t64 libssl3t64 libsodium23 libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

ARG RCLONE_VERSION=v1.71.2
RUN curl -fsSL -o /tmp/rclone.zip https://downloads.rclone.org/$RCLONE_VERSION/rclone-$RCLONE_VERSION-linux-amd64.zip \
 && unzip -j /tmp/rclone.zip '*/rclone' -d /usr/local/bin && rm /tmp/rclone.zip
ARG SEVENZIP_VERSION=26.05
RUN curl -fsSL https://github.com/ip7z/7zip/releases/download/$SEVENZIP_VERSION/7z$(echo $SEVENZIP_VERSION | tr -d .)-linux-x64.tar.xz \
      | tar -xJ -C /usr/local/bin 7zz

ARG KRAM_COMMIT=97c56df
COPY --from=build /opt/megatools /opt/megatools
COPY --from=build /opt/kram/kram /usr/local/bin/kram
COPY --from=build /opt/validate_ktx /usr/local/bin/validate_ktx
ENV PATH=/opt/megatools/bin:$PATH KRAM_VERSION=$KRAM_COMMIT

COPY pyproject.toml /app/
COPY tools /app/tools
RUN pip install --no-deps --break-system-packages /app
COPY scraper/entry.sh /usr/local/bin/entry.sh

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entry.sh"]
