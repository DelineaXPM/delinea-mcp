#!/bin/sh
# Delinea plugin setup helper: finds, installs and prepares uv, which starts
# the Delinea MCP server (`uvx delinea-mcp==<version>`) and provides its
# Python.
#
# Claude runs this only from the /delinea:setup skill, and runs `install`
# only after the user has chosen a method and approved it. Nothing here uses
# sudo, and nothing runs automatically.
#
#   setup-uv.sh check                 Report what's installed and which install
#                                     methods this machine supports (read-only)
#   setup-uv.sh install <method>      Install uv with one method:
#                                     brew | winget | scoop | pipx | pip-venv | official
#   setup-uv.sh link                  If uvx exists but isn't on PATH, link it
#                                     into a user-writable folder that is
#   setup-uv.sh prewarm <spec> [wheel]
#                                     Download the server and Python ahead of
#                                     time, e.g. `prewarm delinea-mcp==2.0.0`

# Status lines echo $(...) output on purpose; a failing probe just prints
# an empty value, which the caller reads as "not found".
# shellcheck disable=SC2312

set -u

VENV_DIR="${HOME}/.local/share/delinea-uv"

os_name() {
    case "$(uname -s 2>/dev/null)" in
    Darwin) echo macos ;;
    MINGW* | MSYS* | CYGWIN*) echo windows ;;
    *) echo linux ;;
    esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# Print the first uvx found on PATH or in a known install location.
find_uvx() {
    if have uvx; then
        command -v uvx
        return 0
    fi
    for candidate in \
        "${HOME}/.local/bin/uvx" "${HOME}/.local/bin/uvx.exe" \
        "${HOME}/.cargo/bin/uvx" "${HOME}/.cargo/bin/uvx.exe" \
        "${VENV_DIR}/bin/uvx" "${VENV_DIR}/Scripts/uvx.exe" \
        /opt/homebrew/bin/uvx /usr/local/bin/uvx \
        "${HOME}/scoop/shims/uvx.exe"; do
        if [ -x "${candidate}" ]; then
            echo "${candidate}"
            return 0
        fi
    done
    return 1
}

python_with_venv() {
    for py in python3 python py; do
        if have "${py}" && "${py}" -c "import venv, ensurepip" >/dev/null 2>&1; then
            echo "${py}"
            return 0
        fi
    done
    return 1
}

# Supported install methods on this machine, most recommended first.
available_methods() {
    os=$(os_name)
    methods=""
    if [ "${os}" = windows ]; then
        have winget || have winget.exe && methods="${methods} winget"
        have scoop && methods="${methods} scoop"
        have powershell.exe && methods="${methods} official"
    else
        [ "${os}" = macos ] && have brew && methods="${methods} brew"
        { have curl || have wget; } && methods="${methods} official"
        [ "${os}" = linux ] && have brew && methods="${methods} brew"
    fi
    have pipx && methods="${methods} pipx"
    python_with_venv >/dev/null && methods="${methods} pip-venv"
    echo "${methods}" | sed 's/^ //'
}

cmd_check() {
    echo "os=$(os_name)"
    if have uvx; then
        echo "uvx=$(command -v uvx)"
        echo "uvx_on_path=yes"
        echo "uv_version=$(uvx --version 2>/dev/null | head -n 1)"
    elif found=$(find_uvx); then
        echo "uvx=${found}"
        echo "uvx_on_path=no"
        echo "uv_version=$("${found}" --version 2>/dev/null | head -n 1)"
    else
        echo "uvx="
        echo "uvx_on_path=no"
    fi
    methods=$(available_methods)
    echo "methods=${methods}"
    echo "recommended=${methods%% *}"
}

cmd_install() {
    method=${1-}
    available=$(available_methods)
    case " ${available} " in
    *" ${method} "*) ;;
    *)
        if [ -n "${available}" ]; then
            echo "Method '${method}' isn't available on this machine. Available: ${available}" >&2
        else
            echo "No install method is available: this machine has no package manager uv supports, no curl or wget, and no Python with venv. Install one of those, or install uv manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
        fi
        return 2
        ;;
    esac
    case "${method}" in
    brew) brew install uv ;;
    winget)
        # Non-interactive winget needs the package and source agreements
        # accepted; the skill tells the user before they approve this.
        winget install --id=astral-sh.uv -e --accept-package-agreements --accept-source-agreements
        ;;
    scoop) scoop install main/uv ;;
    pipx) pipx install uv ;;
    pip-venv)
        # uv from PyPI inside a private virtual environment: works where the
        # system Python refuses `pip install` (PEP 668) and needs no admin rights.
        py=$(python_with_venv) || {
            echo "No Python with the venv module found." >&2
            return 1
        }
        "${py}" -m venv "${VENV_DIR}" || return 1
        if [ -x "${VENV_DIR}/bin/python" ]; then
            "${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check --quiet uv
        else
            "${VENV_DIR}/Scripts/python.exe" -m pip install --disable-pip-version-check --quiet uv
        fi
        ;;
    official)
        if [ "$(os_name)" = windows ]; then
            powershell.exe -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        else
            # Download first so a failed download stops here instead of piping
            # an empty or partial script into sh.
            installer=$(mktemp) || return 1
            if have curl; then
                curl -LsSf https://astral.sh/uv/install.sh -o "${installer}"
            else
                wget -qO "${installer}" https://astral.sh/uv/install.sh
            fi || {
                rm -f "${installer}"
                echo "Couldn't download uv's installer from astral.sh." >&2
                return 1
            }
            sh "${installer}"
            status=$?
            rm -f "${installer}"
            [ "${status}" -eq 0 ] || return "${status}"
        fi
        ;;
    *)
        echo "Unknown method '${method}'. Available here: $(available_methods)" >&2
        return 2
        ;;
    esac
    status=$?
    [ "${status}" -ne 0 ] && return "${status}"
    found=$(find_uvx) || {
        echo "The installer finished but uvx wasn't found." >&2
        return 1
    }
    echo "installed uvx=${found} ($("${found}" --version 2>/dev/null | head -n 1))"
}

cmd_link() {
    if have uvx; then
        echo "uvx is already on PATH: $(command -v uvx)"
        return 0
    fi
    found=$(find_uvx) || {
        echo "uvx isn't installed; run 'install' first." >&2
        return 1
    }
    if [ "$(os_name)" = windows ]; then
        echo "uvx is at ${found} but not on PATH. Add $(dirname "${found}") to your user PATH in Windows settings, then restart Claude Code." >&2
        return 3
    fi
    src_dir=$(dirname "${found}")
    # First user-writable folder that's already on PATH, preferring your home.
    target=""
    for dir in "${HOME}/.local/bin" "${HOME}/bin" /opt/homebrew/bin /usr/local/bin; do
        case ":${PATH}:" in *":${dir}:"*) ;; *) continue ;; esac
        if [ -d "${dir}" ] && [ -w "${dir}" ]; then
            target=${dir}
            break
        fi
    done
    if [ -z "${target}" ]; then
        echo "No user-writable folder on PATH. Add ${src_dir} to PATH in your shell profile, then restart Claude Code from a new terminal." >&2
        return 3
    fi
    for tool in uv uvx; do
        if [ -e "${target}/${tool}" ] && [ ! -L "${target}/${tool}" ]; then
            echo "Not replacing existing ${target}/${tool}" >&2
            continue
        fi
        ln -sf "${src_dir}/${tool}" "${target}/${tool}" && echo "linked ${target}/${tool} -> ${src_dir}/${tool}"
    done
}

cmd_prewarm() {
    spec=${1-}
    wheel=${2-}
    [ -n "${spec}" ] || {
        echo "usage: setup-uv.sh prewarm <spec> [wheel]" >&2
        return 2
    }
    uvx_bin=$(find_uvx) || {
        echo "uvx isn't installed; run 'install' first." >&2
        return 1
    }
    # --no-config: ignore uv.toml / [tool.uv] in the user's project, which
    # could otherwise point the download at a different package index (the
    # manifest launches the server with the same flag).
    if [ -n "${wheel}" ]; then
        "${uvx_bin}" --quiet --no-config --from "${wheel}" delinea-mcp --help >/dev/null
    else
        "${uvx_bin}" --quiet --no-config "${spec}" --help >/dev/null
    fi
    status=$?
    if [ "${status}" -eq 0 ]; then
        echo "prewarmed ${spec}: the server and its Python are downloaded"
    else
        echo "Couldn't download ${spec}. Behind a proxy, set HTTPS_PROXY; with TLS inspection, set UV_NATIVE_TLS=1; if Python downloads are blocked, install Python 3.13." >&2
    fi
    return "${status}"
}

case "${1-}" in
check) cmd_check ;;
install)
    shift
    cmd_install "$@"
    ;;
link) cmd_link ;;
prewarm)
    shift
    cmd_prewarm "$@"
    ;;
*)
    echo "usage: setup-uv.sh check | install <method> | link | prewarm <spec> [wheel]" >&2
    exit 2
    ;;
esac
