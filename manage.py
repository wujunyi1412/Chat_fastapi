from __future__ import annotations

import argparse
import re
import secrets
import sys

from app import database as db
from app.security import hash_password


def valid_slug(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,31}", value):
        raise argparse.ArgumentTypeError("房间标识需为 2–32 位小写字母、数字、_ 或 -")
    return value


def get_room_or_exit(slug: str) -> dict:
    room = db.get_room_by_slug(slug)
    if not room:
        raise SystemExit(f"房间不存在：{slug}")
    return room


def command_create_room(args: argparse.Namespace) -> None:
    from app.database import connect, utc_now
    try:
        with connect() as conn:
            conn.execute("INSERT INTO rooms(slug, name, created_at) VALUES (?, ?, ?)", (args.slug, args.name.strip(), utc_now()))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise SystemExit(f"房间已存在：{args.slug}") from None
        raise
    print(f"已创建房间：{args.name} ({args.slug})")


def command_add_user(args: argparse.Namespace) -> None:
    from app.database import connect, utc_now
    room = get_room_or_exit(args.room)
    password = args.password or secrets.token_urlsafe(10)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO users(room_id, username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (room["id"], args.username.strip(), args.display_name.strip(), hash_password(password), utc_now()),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise SystemExit(f"账号已存在：{args.username}") from None
        raise
    print(f"已添加账号：房间={args.room} 账号={args.username} 昵称={args.display_name}")
    if not args.password:
        print(f"随机密码={password}（只显示这一次，请立即保存）")


def command_set_password(args: argparse.Namespace) -> None:
    from app.database import connect
    room = get_room_or_exit(args.room)
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE room_id = ? AND username = ?",
            (hash_password(args.password), room["id"], args.username),
        )
    if not cursor.rowcount:
        raise SystemExit("账号不存在")
    print("密码已更新")


def command_list(args: argparse.Namespace) -> None:
    from app.database import connect
    with connect() as conn:
        rooms = conn.execute("SELECT id, slug, name, created_at FROM rooms ORDER BY id").fetchall()
        for room in rooms:
            print(f"\n[{room['slug']}] {room['name']}")
            users = conn.execute("SELECT username, display_name, is_active FROM users WHERE room_id=? ORDER BY id", (room["id"],)).fetchall()
            for user in users:
                print(f"  - {user['username']} / {user['display_name']} / {'启用' if user['is_active'] else '停用'}")


def command_disable(args: argparse.Namespace) -> None:
    from app.database import connect
    room = get_room_or_exit(args.room)
    with connect() as conn:
        cursor = conn.execute("UPDATE users SET is_active=0 WHERE room_id=? AND username=?", (room["id"], args.username))
    if not cursor.rowcount:
        raise SystemExit("账号不存在")
    print("账号已停用，现有会话也将失效")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="私语间管理工具")
    sub = parser.add_subparsers(dest="command", required=True)
    room = sub.add_parser("create-room", help="创建房间")
    room.add_argument("slug", type=valid_slug, help="登录时使用的房间标识")
    room.add_argument("name", help="显示名称")
    room.set_defaults(func=command_create_room)
    user = sub.add_parser("add-user", help="给房间添加账号")
    user.add_argument("room", type=valid_slug)
    user.add_argument("username")
    user.add_argument("display_name")
    user.add_argument("--password", help="不提供则生成随机密码")
    user.set_defaults(func=command_add_user)
    password = sub.add_parser("set-password", help="修改账号密码")
    password.add_argument("room", type=valid_slug)
    password.add_argument("username")
    password.add_argument("password")
    password.set_defaults(func=command_set_password)
    listing = sub.add_parser("list", help="列出房间和账号")
    listing.set_defaults(func=command_list)
    disable = sub.add_parser("disable-user", help="停用账号")
    disable.add_argument("room", type=valid_slug)
    disable.add_argument("username")
    disable.set_defaults(func=command_disable)
    return parser


if __name__ == "__main__":
    db.init_db()
    arguments = build_parser().parse_args()
    try:
        arguments.func(arguments)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None

