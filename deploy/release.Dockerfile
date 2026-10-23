# The release image: what a server needs besides the app images to run one commit
# (compose file, config/, postgres init scripts, deploy/). CI builds it from the repo
# root and pushes it as RELEASE_IMAGE:<commit>; bin/deploy-entry copies /release out
# of it. Never run.
FROM scratch
COPY docker-compose.yml /release/
COPY config /release/config
COPY docker/postgres/init /release/docker/postgres/init
COPY deploy /release/deploy
