#!/bin/sh
# Select, or optionally install, one complete LLVM 21 tool prefix.
set -eu

repo=$(git rev-parse --show-toplevel)
env_file="$repo/.llvm21-env"

select_prefix()
{
    if test -n "${LLVM_TOOLS_INSTALL_DIR:-}"; then
        set -- "$LLVM_TOOLS_INSTALL_DIR"
    else
        set -- /opt/llvm-21.1.8 /usr/lib/llvm-21
    fi
    for prefix do
        complete=true
        versions=
        for tool in clang llvm-readobj llvm-objdump llvm-dwarfdump; do
            if ! test -x "$prefix/bin/$tool"; then
                echo "Ignoring incomplete LLVM prefix $prefix: missing $tool" >&2
                complete=false
                continue
            fi
            version_file="${TMPDIR:-/tmp}/ensure-llvm21-version.$$"
            if ! "$prefix/bin/$tool" --version >"$version_file" 2>&1; then
                echo "Ignoring unusable LLVM prefix $prefix: $tool --version failed" >&2
                cat "$version_file" >&2
                rm -f "$version_file"
                complete=false
                continue
            fi
            version=$(sed -n '1p' "$version_file")
            rm -f "$version_file"
            case "$version" in
                *"version 21."*) ;;
                *)
                    echo "Ignoring incompatible LLVM prefix $prefix: $tool reports: $version" >&2
                    complete=false
                    continue
                    ;;
            esac
            if test -z "$versions"; then
                versions=$version
            else
                versions="$versions
$version"
            fi
        done
        if "$complete"; then
            tmp_env="$env_file.tmp.$$"
            trap 'rm -f "$tmp_env"' EXIT HUP INT TERM
            case "$prefix" in
                *"'"*)
                    echo "LLVM prefix contains an unsupported single quote: $prefix" >&2
                    return 1
                    ;;
            esac
            printf "export LLVM_TOOLS_INSTALL_DIR='%s'\n" "$prefix" >"$tmp_env"
            mv "$tmp_env" "$env_file"
            trap - EXIT HUP INT TERM
            echo "Selected complete LLVM prefix: $prefix"
            printf '%s\n' "$versions"
            return 0
        fi
    done
    return 1
}

if select_prefix; then
    exit 0
fi

if test "${1:-}" != --install; then
    cat >&2 <<EOF
No complete LLVM 21 prefix was found.
Checked LLVM_TOOLS_INSTALL_DIR, /opt/llvm-21.1.8, and /usr/lib/llvm-21.
Run $0 --install as root to install the signed apt.llvm.org packages, or set
LLVM_TOOLS_INSTALL_DIR to a prefix containing clang, llvm-readobj,
llvm-objdump, and llvm-dwarfdump.
EOF
    exit 1
fi

test "$(id -u)" -eq 0 || {
    echo "$0 --install must run as root" >&2
    exit 1
}
curl -fsSL --retry 4 --retry-delay 3 \
    https://apt.llvm.org/llvm-snapshot.gpg.key \
    -o /usr/share/keyrings/apt.llvm.org.asc
printf '%s\n' \
    'deb [signed-by=/usr/share/keyrings/apt.llvm.org.asc] https://apt.llvm.org/jammy/ llvm-toolchain-jammy-21 main' \
    >/etc/apt/sources.list.d/llvm21-jammy.list
apt-get update
attempt=1
while ! apt-get install -y --fix-missing clang-21 llvm-21 llvm-21-tools; do
    if test "$attempt" -ge 4; then
        echo "LLVM package installation failed after $attempt attempts" >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    echo "Retrying transient package download failure ($attempt/4)" >&2
    sleep 3
done
select_prefix || {
    echo "Installation completed but /usr/lib/llvm-21 is incomplete" >&2
    exit 1
}
