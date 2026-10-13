# 私语间：Ubuntu 私有聊天室

这是一个适合放在单台 Ubuntu 公网服务器上的轻量聊天室。每个房间有独立账号和密码，房间之间的消息与图片互相隔离。

本项目不使用 systemd，也不会设置开机自启。程序直接从项目目录运行，并由 `tmux` 保持在后台。服务器重启后，需要手动重新启动聊天程序。

运行环境：Ubuntu 22.04/24.04、Python 3.10 或更高版本、一个已经解析到服务器公网 IP 的域名。

## 功能

- 多个独立房间，每个房间可创建多个账号
- Argon2 密码哈希和同 IP 登录失败限速
- WebSocket 实时文字消息、在线人数和正在输入状态
- JPG、PNG、WebP 图片发送与预览
- 图片经过重新编码清除元数据，并且只有对应房间成员能访问
- 历史消息、回复消息、删除自己的消息
- 查看历史记录时不会被新消息强制拉到底部，并提供新消息提示按钮
- 常用表情选择器、后台标签未读数和浏览器桌面通知
- 手机和桌面自适应、断线自动重连
- SQLite 单文件数据库；数据库和图片都在项目的 `data/` 目录
- 命令行管理账号，不对公网开放管理后台

---

# 从零开始部署

下面假设：

- 公网 IP 是 `1.2.3.4`
- 域名是 `chat.example.com`
- SSH 用户名是 `ubuntu`
- 项目最终放在 `~/private-chat`

这些都是示例。执行命令时请换成你自己的信息，尤其不要原样使用 `chat.example.com`。

## 第 1 步：配置域名解析

登录购买域名的网站，在 DNS 管理页面添加一条记录：

```text
类型：A
主机记录：chat
记录值：1.2.3.4
```

如果完整域名就是 `example.com`，主机记录一般填写 `@`；如果使用 `chat.example.com`，主机记录填写 `chat`。不要添加 AAAA 记录，除非服务器确实配置了可用的公网 IPv6。

等待解析生效后，在自己电脑上检查：

```bash
nslookup chat.example.com
```

结果应当包含服务器公网 IP。域名解析不正确时，后面的 HTTPS 证书申请会失败。

## 第 2 步：把 ZIP 上传到服务器

在 Windows PowerShell 中进入 ZIP 所在目录，然后执行：

```powershell
scp .\private-chat.zip ubuntu@1.2.3.4:~/
```

这会把压缩包上传到远程用户的家目录。随后登录服务器：

```powershell
ssh ubuntu@1.2.3.4
```

如果服务器使用 SSH 密钥，给 `scp` 和 `ssh` 增加 `-i 密钥文件路径`。

## 第 3 步：安装系统工具

在 Ubuntu 服务器中执行：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx tmux unzip snapd
```

各工具的用途：

- `python3-venv`：为项目创建独立 Python 环境，避免影响系统 Python。
- `nginx`：接收公网的 80/443 请求，再转给本机 8000 端口。
- `tmux`：退出 SSH 后仍让聊天程序继续运行。
- `unzip`：解压项目。
- `snapd`：安装 Certbot，用来申请 HTTPS 证书。

确认 Python 版本：

```bash
python3 --version
```

应显示 Python 3.10 或更高版本。

## 第 4 步：解压项目

```bash
mkdir -p ~/private-chat
unzip ~/private-chat.zip -d ~/private-chat
cd ~/private-chat
```

第一条命令创建项目目录，第二条解压，第三条进入项目目录。以后没有特别说明时，管理命令都在这个目录执行。

检查文件是否齐全：

```bash
ls
```

应该能看到 `app`、`data`、`deploy`、`manage.py`、`requirements.txt` 等内容。

## 第 5 步：创建 Python 虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

解释：

- `.venv` 是项目自己的 Python 环境，所有第三方包都安装在这里。
- `source` 激活环境后，命令行前面通常会出现 `(.venv)`。
- `requirements.txt` 固定了应用需要的版本。

以后重新登录时不一定要手动激活环境；也可以直接使用 `.venv/bin/python` 和 `.venv/bin/uvicorn`。

## 第 6 步：创建配置文件

复制模板并生成随机密钥：

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

复制第二条命令的输出，然后编辑配置：

```bash
nano .env
```

将配置改成类似下面这样：

```dotenv
CHAT_SECRET_KEY=粘贴刚才生成的随机密钥
CHAT_HOST=0.0.0.0
CHAT_PORT=8000
CHAT_COOKIE_SECURE=true
CHAT_MAX_IMAGE_MB=8
CHAT_HISTORY_PAGE_SIZE=50
```

因为最终使用 HTTPS，所以 `CHAT_COOKIE_SECURE` 设置为 `true`。保存 Nano：按 `Ctrl+O`、回车，再按 `Ctrl+X`。

限制配置文件只有当前用户可以读取：

```bash
chmod 600 .env
```

`.env` 包含会话签名密钥，不要发给别人，也不要上传到公开仓库。

## 第 7 步：创建房间和账号

创建一个房间：

```bash
.venv/bin/python manage.py create-room friends "朋友们"
```

- `friends` 是登录时填写的房间标识，只能使用小写字母、数字、下划线和短横线。
- `朋友们` 是聊天页面显示的名称。

为房间创建账号：

```bash
.venv/bin/python manage.py add-user friends alice "小艾"
.venv/bin/python manage.py add-user friends bob "小博"
```

未提供密码时，程序会生成一个随机密码并且只显示一次。请立即保存，然后把“房间标识、账号、密码”单独发给相应用户。

如果想自己指定密码：

```bash
.venv/bin/python manage.py add-user friends carol "小可" --password '一个至少8位的强密码'
```

密码写在命令中可能进入 Shell 历史，因此更推荐让程序生成随机密码。

查看已有房间和账号：

```bash
.venv/bin/python manage.py list
```

## 第 8 步：用 tmux 启动聊天程序

在项目目录中执行：

```bash
tmux new-session -d -s private-chat "cd '$HOME/private-chat' && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1"
```

这条命令会创建名为 `private-chat` 的后台 tmux 会话，在项目目录启动应用。应用只监听 `127.0.0.1:8000`，所以 8000 端口不会直接暴露到公网。代理参数用于信任本机 Nginx 传来的真实访客地址。

检查 tmux 会话和应用健康状态：

```bash
tmux ls
curl http://127.0.0.1:8000/health
```

健康检查应返回：

```json
{"status":"ok"}
```

查看实时日志：

```bash
tmux attach -t private-chat
```

查看完后按 `Ctrl+B`，松开，再按 `D`，即可退出 tmux 界面但不停止程序。不要直接按 `Ctrl+C`，那会停止程序。

## 第 9 步：配置 Nginx，但不复制配置文件

项目自带的配置位于 `deploy/nginx-domain.conf`。先替换域名占位符：

```bash
sed -i 's/DOMAIN_NAME/chat.example.com/g' deploy/nginx-domain.conf
```

然后从 Nginx 配置目录创建一个指向项目文件的软链接：

```bash
sudo ln -s "$(pwd)/deploy/nginx-domain.conf" /etc/nginx/sites-enabled/private-chat
```

这不是复制文件。`/etc/nginx/sites-enabled/private-chat` 只是链接；以后直接编辑项目中的 `deploy/nginx-domain.conf` 即可。

检查链接和 Nginx 配置：

```bash
readlink -f /etc/nginx/sites-enabled/private-chat
sudo nginx -t
sudo systemctl reload nginx
```

只有看到 `syntax is ok` 和 `test is successful` 才执行 reload。如果测试失败，先根据错误信息修正。

先在服务器本机测试 Nginx 转发：

```bash
curl -H 'Host: chat.example.com' http://127.0.0.1/health
```

应看到 `{"status":"ok"}`。公网访问要等下一步开放防火墙后再测试。

## 第 10 步：开放防火墙端口

先确保 SSH 不会被挡住，再开放网页端口：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

`Nginx Full` 会开放 HTTP 80 和 HTTPS 443。不要关闭 SSH 端口，否则可能无法再次登录。

如果云服务商还有安全组或云防火墙，也要允许 TCP 22、80、443。不需要向公网开放 8000。

## 第 11 步：申请 HTTPS 证书

安装 Certbot：

```bash
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/local/bin/certbot
```

申请证书并让 Certbot 更新当前 Nginx 配置：

```bash
sudo certbot --nginx -d chat.example.com
```

按提示输入邮箱、同意条款，并选择将 HTTP 自动跳转到 HTTPS。Certbot 通过 `/etc/nginx/sites-enabled/private-chat` 的链接读取配置，修改后请再次运行 `sudo nginx -t`，并查看项目中的 `deploy/nginx-domain.conf` 是否已加入证书配置。

测试证书自动续期：

```bash
sudo certbot renew --dry-run
```

成功后访问 `https://chat.example.com`。浏览器应显示锁形图标。不要使用 `http://公网IP` 登录，因为 IP 地址不匹配域名证书。

---

# 日常操作

## 查看程序是否运行

```bash
tmux ls
curl http://127.0.0.1:8000/health
```

## 查看日志

```bash
tmux attach -t private-chat
```

按 `Ctrl+B`，松开，再按 `D` 返回普通终端。

## 停止程序

```bash
tmux send-keys -t private-chat C-c
```

## 再次启动

```bash
cd ~/private-chat
tmux new-session -d -s private-chat "cd '$HOME/private-chat' && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1"
```

服务器重启以后也执行这一段。本项目不会自动启动。

## 修改密码

```bash
cd ~/private-chat
.venv/bin/python manage.py set-password friends alice '新的强密码'
```

## 停用账号

```bash
cd ~/private-chat
.venv/bin/python manage.py disable-user friends alice
```

## 新增另一个房间

```bash
cd ~/private-chat
.venv/bin/python manage.py create-room family "家人群"
.venv/bin/python manage.py add-user family member1 "家人一"
```

不同房间之间看不到彼此的账号、消息和图片。

---

# 备份与恢复

为了保证 SQLite 数据库、WAL 文件和图片一致，先停止程序再备份：

```bash
tmux send-keys -t private-chat C-c
cd ~/private-chat
tar -czf "$HOME/private-chat-backup-$(date +%F-%H%M).tar.gz" data .env deploy/nginx-domain.conf
```

备份文件位于用户家目录，包含聊天记录、图片、密钥和当前 Nginx 配置。备份完成后按“再次启动”重新启动。

恢复时先停止程序，再执行：

```bash
cd ~/private-chat
tar -xzf ~/private-chat-backup-日期时间.tar.gz
```

因为备份包含 `.env`，请像保护密码一样保护备份文件。

---

# 故障排查

## 浏览器显示 502 Bad Gateway

说明 Nginx 正常，但聊天程序没有运行：

```bash
tmux ls
curl http://127.0.0.1:8000/health
```

如果没有 `private-chat` 会话，按“再次启动”启动。

## 域名打不开

```bash
nslookup chat.example.com
sudo nginx -t
sudo systemctl status nginx
sudo ufw status
```

同时检查云服务商安全组是否开放 80 和 443。

## 图片无法上传

默认单张图片上限为 8 MB。应用限制由 `.env` 的 `CHAT_MAX_IMAGE_MB` 控制，Nginx 限制由 `deploy/nginx-domain.conf` 的 `client_max_body_size` 控制。修改 Nginx 配置后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Nginx 软链接已经存在

先查看它指向哪里：

```bash
readlink -f /etc/nginx/sites-enabled/private-chat
```

确认它确实是旧的私语间链接后，才执行：

```bash
sudo unlink /etc/nginx/sites-enabled/private-chat
sudo ln -s "$(pwd)/deploy/nginx-domain.conf" /etc/nginx/sites-enabled/private-chat
```

不要随意删除其他网站的 Nginx 配置。

## 查看 Nginx 错误日志

```bash
sudo tail -f /var/log/nginx/error.log
```

---

# 项目结构

```text
app/
  main.py            HTTP 和 WebSocket 路由
  database.py        SQLite 数据访问
  security.py        密码和登录会话
  rate_limit.py      登录失败限速
  realtime.py        房间实时连接管理
  templates/         HTML 页面
  static/            CSS 和浏览器端 JavaScript
data/
  chat.db            自动创建，保存聊天记录
  uploads/           保存聊天图片
deploy/
  nginx-domain.conf  Nginx 配置；通过软链接启用
manage.py            房间和账号管理工具
.env                 本机配置和会话密钥，不应公开
```

这是单机、小规模私聊版本，适合几十人以内使用。Uvicorn 应保持单进程，因为在线状态和 WebSocket 广播保存在当前进程内。若以后需要多进程或多台服务器，需要加入 Redis。图片不会自动清理，应定期检查磁盘空间。
