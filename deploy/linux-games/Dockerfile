FROM ghcr.io/games-on-whales/steam:edge

USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
      supertux \
      extremetuxracer \
      neverball \
      minetest \
      endless-sky \
      chromium-bsu \
      libgl1 \
      libglu1-mesa \
      libsdl2-2.0-0 \
      libsdl2-image-2.0-0 \
      libsdl2-mixer-2.0-0 \
      libsdl2-ttf-2.0-0 \
      libopenal1 && \
    rm -rf /var/lib/apt/lists/*

# Configure Sway inside the game container for zero-chrome fullscreen console mode
RUN sed -i '/bindsym \$mod+Return/d' /cfg/sway/config && \
    sed -i '/bar swaybar_command/d' /cfg/sway/config && \
    printf '\ngaps inner 0\ngaps outer 0\ndefault_border none\ndefault_floating_border none\noutput * bg #050811 solid_color\nfor_window [class=".*"] fullscreen enable\nfor_window [app_id=".*"] fullscreen enable\n' >> /cfg/sway/config

COPY startup-app.sh /opt/gow/startup-app.sh
RUN chmod 755 /opt/gow/startup-app.sh

