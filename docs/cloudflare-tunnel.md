# Cloudflare Tunnel 公网访问指南

通过 Cloudflare Tunnel（cloudflared）将本地 RecruitFlow 服务暴露到公网，无需开放路由器端口。

## 前置条件

- [x] 已购买的域名（腾讯云 / 阿里云 / GoDaddy 等任意注册商均可）
- [x] Cloudflare 账号（免费套餐）
- [x] Windows 系统，`cloudflared` 已安装

---

## 第一步：将域名 DNS 托管到 Cloudflare

这是最关键的一步——域名的 DNS 解析权必须从注册商（腾讯云）转移到 Cloudflare。

### 1.1 在 Cloudflare 添加站点

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 点击 **"添加站点"（Add a site）**
3. 输入你的域名（例如 `example.com`），点击 **"继续"**
4. 选择 **Free** 套餐，点击 **"继续"**
5. Cloudflare 会自动扫描现有 DNS 记录，点击 **"继续"**

### 1.2 更新 Nameserver（在腾讯云操作）

Cloudflare 会显示两条 Nameserver 地址，类似：

```
alice.ns.cloudflare.com
bob.ns.cloudflare.com
```

1. 登录 [腾讯云 DNSPod 控制台](https://console.cloud.tencent.com/cns)
2. 找到你的域名 → **"更多"** → **"修改 DNS 服务器"**
3. 选择 **"自定义 DNS"**，填入 Cloudflare 提供的两条 Nameserver
4. 保存

> ⚠️ DNS 变更需要 1-24 小时全球生效。期间 Cloudflare 会显示 "Pending Nameserver Update"。
> Cloudflare 通常会在 5-30 分钟内检测到变更。

### 1.3 验证 DNS 已生效

在 Cloudflare  Dashboard 中，站点状态变为 **"Active"** 即表示生效。

也可以命令行验证：

```powershell
nslookup -type=NS 你的域名.com
# 应该显示 alice.ns.cloudflare.com 和 bob.ns.cloudflare.com
```

---

## 第二步：登录并创建 Tunnel

### 2.1 认证 cloudflared

```powershell
cloudflared tunnel login
```

浏览器会自动打开 Cloudflare 授权页面 → 选择你的域名 → 点击 **"Authorize"**。

完成后，证书文件会保存到 `C:\Users\<用户名>\.cloudflared\cert.pem`。

### 2.2 创建 Tunnel

```powershell
cloudflared tunnel create recruitflow
```

输出示例：

```
Tunnel credentials written to C:\Users\xxx\.cloudflared\<tunnel-uuid>.json.
```

记录这个 **Tunnel UUID**（例如 `a1b2c3d4-e5f6-7890-abcd-ef1234567890`）。

---

## 第三步：配置 DNS 路由

将你的子域名指向 Tunnel：

```powershell
cloudflared tunnel route dns recruitflow hr.你的域名.com
```

这会在 Cloudflare DNS 中自动创建一条 CNAME 记录：

```
hr.你的域名.com  →  <tunnel-uuid>.cfargotunnel.com
```

你可以在 Cloudflare Dashboard → DNS 中看到这条记录（橙色云朵图标，表示已代理）。

---

## 第四步：编写 config.yml

在 `C:\Users\<用户名>\.cloudflared\` 下创建 `config.yml`：

```yaml
tunnel: <你的-tunnel-uuid>
credentials-file: C:\Users\<用户名>\.cloudflared\<tunnel-uuid>.json

ingress:
  # RecruitFlow 主服务
  - hostname: hr.你的域名.com
    service: http://localhost:8000

  # 默认拒绝所有其他请求
  - service: http_status:404
```

> 把 `<你的-tunnel-uuid>` 替换为第二步中记录的 UUID。
> 把 `<用户名>` 替换为你的 Windows 用户名。

---

## 第五步：运行 Tunnel 并验证

### 5.1 前台运行测试

先确保 RecruitFlow 在本地运行：

```powershell
# 终端 1：启动 RecruitFlow
.\run.ps1
```

```powershell
# 终端 2：启动 Tunnel
cloudflared tunnel run recruitflow
```

看到 `Registered tunnel connection` 表示连接成功。

### 5.2 验证公网访问

浏览器打开 `https://hr.你的域名.com`，应该能看到 RecruitFlow 登录页面。

Cloudflare 会自动为你的域名签发 SSL 证书（Let's Encrypt），全程 HTTPS。

---

## 第六步：注册为 Windows 服务（开机自启）

前台测试没问题后，注册为系统服务：

```powershell
cloudflared service install
```

这会：
- 在 Windows 服务列表中注册 `Cloudflare Tunnel` 服务
- 设置为**自动启动**（开机自启）
- 后台静默运行

管理命令：

```powershell
# 启动服务
Start-Service cloudflared

# 停止服务
Stop-Service cloudflared

# 查看状态
Get-Service cloudflared

# 卸载服务
cloudflared service uninstall
```

---

## 第七步：安全加固（强烈推荐）

### 7.1 设置 Cloudflare Access（给管理页面加二次验证）

防止任何人访问你的 RecruitFlow 管理后台：

1. Cloudflare Dashboard → **Zero Trust** → **Access** → **Applications**
2. 点击 **"Add an application"** → **"Self-hosted"**
3. 配置：
   - Application name: `RecruitFlow Admin`
   - Subdomain: `hr.你的域名.com`
   - 勾选 **"Accept all available identity providers"**（使用邮箱一次性验证码）
4. Policy：允许的邮箱地址（你自己的邮箱）
5. 保存

现在访问 `https://hr.你的域名.com` 时，会先要求输入邮箱 → 收到验证码 → 才能进入登录页面。

### 7.2 WAF 规则（IP 白名单）

如果只有你一个人访问：

1. Cloudflare Dashboard → **Security** → **WAF** → **Custom Rules**
2. 创建规则：`(not ip.src eq 你的静态IP) and (not cf.client.bot)`
3. 动作：**Block**

### 7.3 速率限制

保护 LLM API 不被滥用：

1. Cloudflare Dashboard → **Security** → **Rate Limiting**
2. 创建规则，路径 `/api/agent/chat`，限制每分钟 10 次请求

### 7.4 SSL/TLS 设置

1. Cloudflare Dashboard → **SSL/TLS** → **Overview**
2. 选择 **"Full (strict)"** 模式

---

## Docker Compose 集成（可选）

如果希望 cloudflared 和应用一起启动，在 `docker-compose.yml` 中添加：

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    network_mode: host
    restart: unless-stopped
```

然后在 `.env` 中添加 `CLOUDFLARE_TUNNEL_TOKEN`（在 Cloudflare Dashboard → Zero Trust → Tunnels → 点击你的隧道 → 可以获取 Token）。

> 用 Token 方式不需要挂载 credentials 文件，更安全。

---

## 故障排查

### Tunnel 连接失败

```powershell
# 查看 Tunnel 详情
cloudflared tunnel info recruitflow

# 查看服务日志（如果注册了服务）
Get-EventLog -LogName Application -Source cloudflared -Newest 50
```

### 502 Bad Gateway

说明 Tunnel 连接正常，但本地服务有问题：
- 确认 `http://localhost:8000` 可以访问
- 确认 `config.yml` 中 `service` 地址写的是 `http://localhost:8000`

### DNS 解析不到

```powershell
# 检查 DNS 记录
nslookup hr.你的域名.com

# 检查 Cloudflare 代理状态
# Dashboard → DNS → 橙色云朵图标必须是亮的
```

### 域名 Nameserver 未生效

```powershell
# 查看当前 Nameserver
nslookup -type=NS 你的域名.com
```

如果不是 Cloudflare 的 Nameserver，说明腾讯云侧还没改好，或 DNS 还在传播中（最多 24 小时）。

---

## 费用说明

| 项目 | 费用 |
|---|---|
| Cloudflare Tunnel | **免费** |
| Cloudflare DNS | **免费** |
| SSL 证书 | **免费**（自动签发） |
| DDoS 防护 | **免费** |
| Cloudflare Access（邮箱验证） | **免费**（最多 50 用户） |
| 域名 | 腾讯云按年收费（约 ¥30-60/年） |
