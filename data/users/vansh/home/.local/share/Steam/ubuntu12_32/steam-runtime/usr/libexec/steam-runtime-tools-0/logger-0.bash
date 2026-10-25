#!/usr/bin/env bash
# Intended to be sourced (not executed), see srt-logger(1) for usage

# Copyright © 2024 Collabora Ltd
# SPDX-License-Identifier: MIT

case "${0##*/}" in
    (logger-0.bash | srt-logger-0.bash)
        echo "srt-logger-0.bash should be sourced, not executed" >&2
        echo "Usage: . $0 [SRT-LOGGER OPTIONS]" >&2
        exit 1
esac

_srt_redirect_log () {
    local fifo
    local log_to_stdin
    local logger="${SRT_LOGGER-}"
    local result=1
    local status_from_stdout
    local this_file="${BASH_SOURCE[0]}"

    # Set by `eval`
    # shellcheck disable=SC2034
    local SRT_LOGGER_PID
    # shellcheck disable=SC2034
    local SRT_LOGGER_READY

    if [ -z "$logger" ]; then
        logger="${this_file%/*}/srt-logger"
    fi

    if ! fifo=$("$logger" --mkfifo); then
        return 1
    fi

    exec {log_to_stdin}> >(
        # block until parent opens the fifo for reading
        exec > "$fifo"

        exec "$logger" --background --sh-syntax "$@"
    )

    # block until child opens the fifo for writing, then both proceed
    exec {status_from_stdout}< "$fifo"

    # fifo no longer needs to exist after both sides have opened it
    if rm -f "$fifo"; then
        rmdir "${fifo%/*}" || :
    fi

    output="$(cat <&${status_from_stdout})"
    exec {status_from_stdout}<&-

    if [ "${output%SRT_LOGGER_READY=1}" != "$output" ] && eval "$output"; then
        exec >&${log_to_stdin}
        exec 2>&1
        result=0
    fi

    exec {log_to_stdin}>&-
    return "$result"
}

_srt_redirect_log "$@"
