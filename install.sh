#!/bin/sh
# Bole 环境体检：只检测并给出指引，绝不自动安装。

set -u

ok=0
warn=0

pass() {
  printf '✓ %s\n' "$1"
  ok=$((ok + 1))
}

notice() {
  printf '! %s\n' "$1"
  warn=$((warn + 1))
}

printf 'Bole（伯乐）环境检查\n\n'

if command -v python3 >/dev/null 2>&1; then
  py_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    pass "Python $py_version（满足 ≥ 3.10）"
  else
    notice "Python $py_version 过旧；请安装 Python 3.10 或更高版本。"
  fi
else
  notice "未找到 python3；请从 https://www.python.org/downloads/ 安装 Python ≥ 3.10。"
fi

if command -v claude >/dev/null 2>&1; then
  claude_version=$(claude --version 2>/dev/null | head -n 1)
  pass "Claude Code CLI：${claude_version:-已安装}"
else
  notice "未找到 claude；请先按 Claude Code 官方说明安装并登录。"
fi

browser=''
for candidate in google-chrome chromium chromium-browser microsoft-edge msedge; do
  if command -v "$candidate" >/dev/null 2>&1; then
    browser=$candidate
    break
  fi
done
if [ -n "$browser" ]; then
  pass "PDF 浏览器：$browser"
else
  notice "未找到 Chrome/Chromium/Edge；Bole 仍会生成 HTML，可在浏览器中 Ctrl+P 另存为 PDF。"
fi

if command -v node >/dev/null 2>&1; then
  node_version=$(node --version 2>/dev/null)
  node_major=$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null)
  if [ -n "$node_major" ] && [ "$node_major" -ge 18 ] 2>/dev/null; then
    pass "Node.js：${node_version:-已安装}（满足自动投递所需 ≥ 18）"
  else
    notice "Node.js ${node_version:-版本未知} 过旧；/apply 需要 Node ≥ 18，核心功能不受影响。"
  fi
else
  notice "未找到 Node.js（仅 /apply 自动投递需要，核心功能不受影响）。"
fi

if command -v openclaw >/dev/null 2>&1; then
  openclaw_version=$(openclaw --version 2>/dev/null | head -n 1)
  pass "OpenClaw：${openclaw_version:-已安装}（自动投递默认关闭）"
else
  notice "未找到 OpenClaw（可选）；启用 /apply 前可自行运行：npm install -g openclaw"
fi

printf '\n检查完成：%s 项通过，%s 项需留意。\n' "$ok" "$warn"
printf '本脚本没有安装或修改任何系统组件。下一步：在本目录运行 claude，然后输入 /doctor。\n'
exit 0
