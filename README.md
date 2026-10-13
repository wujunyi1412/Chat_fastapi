# 私语间：轻量私有聊天室

适合部署在一台 Ubuntu 公网服务器上的多房间聊天应用。每个房间拥有自己的一组账号；房间之间的消息和图片完全隔离。

运行环境要求：Ubuntu 22.04/24.04，Python 3.10 或更高版本。

## 已有功能

- 房间 + 账号 + 密码登录，Argon2 密码哈希
- 同一 IP 登录失败限速，降低公网密码爆破风险
- WebSocket 实时文字消息、在线人数和“正在输入”状态
- JPG / PNG / WebP 图片发送、预览和权限保护
- 历史消息分页、回复消息、删除自己的消息
- 手机与桌面自适应界面、掉线自动重连
- SQLite 单文件数据库；数据、图片均在项目的 `data/` 内
- 纯命令行管理房间和账号，不暴露公网管理后台

## Ubuntu 部署

以下假设项目目录为 `/opt/private-chat`，系统账号为 `chatapp`。如果目录或账号不同，替换相应内容。

```bash
sudo apt update
sudo apt install -y python3-venv nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin chatapp
sudo mkdir -p /opt/private-chat
sudo chown -R chatapp:chatapp /opt/private-chat
```

把整个项目上传至 `/opt/private-chat` 后：

```bash
cd /opt/private-chat
sudo -u chatapp python3 -m venv .venv
sudo -u chatapp .venv/bin/pip install -r requirements.txt
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

把最后一条命令生成的随机字符串填入 `.env` 的 `CHAT_SECRET_KEY`。首次启动前创建房间和账号：

```bash
sudo -u chatapp .venv/bin/python manage.py create-room friends "朋友们"
sudo -u chatapp .venv/bin/python manage.py add-user friends alice "小艾"
sudo -u chatapp .venv/bin/python manage.py add-user friends bob "小博"
```

未写 `--password` 时会生成一次性显示的随机密码。也可以显式指定：

```bash
sudo -u chatapp .venv/bin/python manage.py add-user friends carol "小可" --password '一个至少8位的强密码'
```

### 配置 systemd

复制模板，并替换其中两个占位符：

```bash
sudo cp deploy/chat.service /etc/systemd/system/private-chat.service
sudo sed -i 's|CHAT_USER|chatapp|g; s|CHAT_PROJECT_DIR|/opt/private-chat|g' /etc/systemd/system/private-chat.service
sudo systemctl daemon-reload
sudo systemctl enable --now private-chat
sudo systemctl status private-chat
curl http://127.0.0.1:8000/health
```

### 配置 Nginx 和防火墙

```bash
sudo cp deploy/nginx-ip.conf /etc/nginx/sites-available/private-chat
sudo sed -i 's/SERVER_IP/你的公网IP/g' /etc/nginx/sites-available/private-chat
sudo ln -s /etc/nginx/sites-available/private-chat /etc/nginx/sites-enabled/private-chat
sudo nginx -t
sudo systemctl reload nginx
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx HTTP'
sudo ufw enable
```

浏览器访问 `http://你的公网IP`，输入房间标识、账号和密码。

> **重要安全提示：** 只有 IP 且使用 HTTP 时，登录密码和聊天内容在网络上不是加密传输。短期测试可以如此使用；正式给别人使用前，强烈建议买一个便宜域名、解析到该 IP，并用 Certbot 或 Caddy 配置 HTTPS。启用 HTTPS 后，把 `.env` 中 `CHAT_COOKIE_SECURE` 改为 `true` 并重启服务。

## 日常管理

都在项目目录执行：

```bash
# 查看所有房间和账号（不会显示密码）
sudo -u chatapp .venv/bin/python manage.py list

# 修改密码
sudo -u chatapp .venv/bin/python manage.py set-password friends alice '新的强密码'

# 停用账号
sudo -u chatapp .venv/bin/python manage.py disable-user friends alice

# 查看日志 / 重启
sudo journalctl -u private-chat -f
sudo systemctl restart private-chat
```

## 备份与迁移

停止服务后打包 `data/` 和 `.env` 即可获得一致的完整备份：

```bash
sudo systemctl stop private-chat
sudo tar -czf private-chat-backup-$(date +%F).tar.gz -C /opt/private-chat data .env
sudo systemctl start private-chat
```

恢复时把它们解压回项目根目录，并确保所有者是 `chatapp:chatapp`。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 中的 CHAT_SECRET_KEY
python manage.py create-room demo "演示房间"
python manage.py add-user demo tester "测试员" --password 'test-pass-123'
uvicorn app.main:app --reload
```

Windows PowerShell 激活虚拟环境使用 `.venv\Scripts\Activate.ps1`。

## 目录结构

```text
app/
  main.py          HTTP、WebSocket 路由
  database.py      SQLite 数据访问
  security.py      密码和会话
  realtime.py      房间连接管理
  templates/       页面模板
  static/          样式和聊天交互
data/
  chat.db          自动创建（聊天记录）
  uploads/         图片
deploy/            systemd 与 Nginx 模板
manage.py          房间/账号管理命令
```

## 当前适用范围

这是单机、小规模私聊版本，适合几十人以内使用。Uvicorn 应保持单 worker，因为在线状态和 WebSocket 广播保存在单进程内；如果以后要扩展为多进程或多台服务器，需要加入 Redis。图片没有自动过期策略，需留意服务器磁盘空间。
