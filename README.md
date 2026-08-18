# 🍊 医疗岗位雷达

一个面向心血管内科临床医生的医疗岗位聚合工具，像"丁香人才的小号版"，
但专注于 **体检科 / 心电图 / 社区 / 校医 / 卫健委 / 疾控 / AI 医疗** 这几类方向。

## 核心功能

| 功能 | 说明 |
|---|---|
| 🔍 卡片式浏览 | 按类别/城市/可靠性/编内筛选，支持关键词搜索 |
| 📥 粘贴抓取 | 从浏览器复制搜索结果列表 → 粘贴 → 自动识别入库 |
| 🌐 URL 自动识别 | 填一个公告链接 → 自动抓页面回填表单 |
| 🌐 **Tavily 联网搜索** | 配置 API key 后，一键让程序自动搜索 6 类岗位 × 东莞/广州/深圳 |
| ⏰ **每日自动抓取** | 部署到云端后，每天早上 08:00 自动跑一次 |
| 🧹 过期扫描 | 主动把已过截止日期的岗位标过期 |
| 🔗 链接巡检 | 定时访问每条岗位 URL，404 自动过期 |
| 📤 CSV/JSON 导出 | Excel 直接打开 |
| 🏷 用户状态 | 已读 / 收藏 / 已投递，浏览器本地记忆 |

## 三种使用方式

### 方式 1：本地使用（最快上手）

#### 一键启动
1. 双击 `start.bat`
2. 浏览器会自动打开 http://127.0.0.1:5173

#### 同 wifi 手机访问
`start.bat` 启动后会显示本机 IP（如 `192.168.1.100`），
手机连同一 wifi 后在浏览器输入 `http://192.168.1.100:5173` 即可访问。

#### 启用 Tavily 自动联网搜索（可选）
1. 去 https://tavily.com 注册（免费 1000 次/月，够用）
2. 在 start.bat 的 `set "HOST=0.0.0.0"` 下面加一行：
   ```bat
   set TAVILY_API_KEY=tvly-你的key
   set ENABLE_SCHEDULER=1
   ```
3. 重启 start.bat
4. 在小程序里点 `🌐 自动联网搜索` 即可一键联网

#### 停止服务
双击 `stop.bat`

### 方式 2：云端部署（手机随时打开，免费）

把项目推到 GitHub → 在 Render.com 一键部署，全程 5 分钟。

#### 步骤
1. 注册 GitHub：https://github.com
2. 把 `岗位雷达小程序/` 整个目录上传到一个新仓库
3. 注册 Render：https://render.com（用 GitHub 登录）
4. Render 控制台 → `New` → `Blueprint` → 选你的仓库
5. Render 自动读取 `render.yaml`，5 分钟内给你一个 https://xxx.onrender.com 地址
6. 手机浏览器收藏这个地址，全球任何地方 4G/Wifi 都能访问

#### 云端配置 Tavily 自动搜索
在 Render 控制台 → Environment → 添加：
- `TAVILY_API_KEY` = `tvly-你的key`
- `ENABLE_SCHEDULER` = `1`

云端每天 08:00 自动跑 Tavily 搜索，再也不需要手动操作。

#### 注意
- Render 免费层 15 分钟无访问会休眠，下次访问要等 5-10 秒唤醒
- 数据存在 Render 的临时磁盘，**会定期清空**——重要岗位记得收藏或导出 CSV

### 方式 3：Docker 自托管（自己控制数据）

适合有自己的服务器/树莓派的用户：

```bash
docker build -t chen-job-radar .
docker run -d -p 5173:5173 \
  -v $(pwd)/data:/app/data \
  -e TAVILY_API_KEY=tvly-xxx \
  -e ENABLE_SCHEDULER=1 \
  --restart=always \
  --name chen-job-radar \
  chen-job-radar
```

## 文件结构

```
岗位雷达小程序/
├── app.py            Flask 主入口（API 路由）
├── wsgi.py           Gunicorn 云端入口
├── database.py       SQLite 模型
├── parser.py         文本/URL 智能解析
├── crawler.py        抓取任务（含 Tavily 集成 + 过期扫描 + 链接巡检 + 后台调度）
├── templates/
│   └── index.html    单页应用
├── static/
│   ├── css/style.css
│   └── js/app.js
├── start.bat         Windows 一键启动
├── stop.bat          Windows 停止服务
├── Dockerfile        容器化部署
├── render.yaml       Render.com 一键部署
├── requirements.txt  Python 依赖
├── .gitignore        Git 忽略
├── jobs.db           SQLite 数据库（运行时生成）
└── tools/            一次性 ETL 脚本（不影响主程序）
```

## API 端点速查

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 单页应用 |
| GET | `/api/jobs?category=心电图&city=东莞&hide_expired=1` | 岗位列表（多条件筛选） |
| POST | `/api/jobs` | 添加岗位 |
| PATCH | `/api/jobs/{id}` | 修改状态 |
| DELETE | `/api/jobs/{id}` | 删除 |
| POST | `/api/crawl/paste` | 粘贴文本 → 入库 |
| POST | `/api/crawl/fetch-url` | 给一个 URL → 自动识别回填 |
| POST | `/api/crawl/tavily` | 联网搜索（需 key） |
| POST | `/api/crawl/sweep` | 扫描过期 |
| POST | `/api/crawl/deadlinks` | 链接巡检 |
| GET | `/api/stats` | 统计 |
| GET | `/api/crawl-logs` | 抓取日志 |
| GET | `/api/export?format=csv` | 导出 |
| GET | `/api/health` | 健康检查 |

## 常见问题

**Q: 第二天就打不开？**
A: 你可能在用 IDE 启动 Flask，IDE 关闭后进程被杀。改用 `start.bat` 启动，进程独立运行。

**Q: 数据库被清空了？**
A: 云端部署的免费层磁盘是临时的。要持久化请用 Docker 自托管方式，绑定 `-v` 数据卷。

**Q: Tavily 联网搜索要不要钱？**
A: 注册就送 1000 次/月，足够日常使用（每天跑 1 次，约用 14 个关键词 × 8 结果 = 112 次/天）。

**Q: 怎么找新岗位不靠 Tavily？**
A: `📥 粘贴抓取` 是最稳的方式。打开浏览器，搜「体检科医师 招聘 2026」，
选中前 10 条结果标题+URL 复制，回到小程序粘贴 → 入库。30 秒搞定。

**Q: 之前手动添加的岗位怎么办？**
A: 都存在 `jobs.db` 里。打包整个目录或导出 CSV 就能备份。