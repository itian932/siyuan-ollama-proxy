# 介绍

本项目主要包含 思源无登录版 + 本地ollama + ollama代理。
主要用于解决思源siyuan-plugin-publisher插件的AI无model参数导致的报错无法使用。

# 启动

默认使用GPU，如无英伟达显卡，docker-compose.yml可以注释掉GPU配置。
```bash
docker compose up -d --build
```

# 配置

## siyuan

### 设置语言
*设置*->*Appearance*->*Language*->*简体中文*

### 云端同步

使用的是[CloudFlare](https://dash.cloudflare.com)的R2存储服务，插件存储桶，然后在*R2 对象存储*首页右下角的*API Tokens*点击*Manage*创建一个*帐户 API 令牌*，给予*管理员读和写*权限，并填入思源->*设置*->*云端*页面。

对应关系如下：

| 思源 | R2 |
|:--:|:--:|
| Endpoint | 终结点 |
| Access Key | 访问密钥 ID |
| Secret Key | 机密访问密钥 |
| Bucket | 存储桶名称 |
| Region ID | auto/不填 |
| Concurrent Reqs（同步线程数） | 16 |

然后点击*启用云端同步*
如果是主同步设备到云端的，需要在思源->*关于*->*数据仓库密钥*点击生成*自动生成密钥*，其他从同步设备就可以从这里获取到的密钥，来*导入密钥*并配置相同的*云端*即可同步到其他设备进行绑定。

### 思源AI

*设置*->*AI*
| key | value |
|:--:|:--:|
| 模型 | 推荐 llama3.1、deepseek-r1、qwen3 |
| API Key | 本地ollama随便填 |
| API 基础地址 | http://ollama:11434/v1 |

### 插件系列

http://localhost:18000/v1?model=qwen3:8b

## ollama

[ollama](https://ollama.com/)是一个本地运行AI大模型的平台，里面的大模型都是可以直接下载到本地使用的（根据自己主机的配置来）。

### 常用命令

以deepseek-r1:8b模型为例。

1. 查看本地已安装的模型
```bash
ollama list
```
2. 下载指定模型
```bash
ollama pull deepseek-r1:8b
```

3. 运行模型
```bash
ollama run deepseek-r1:8b
```

4. 删除模型
```bash
ollama rm deepseek-r1:8b
```

5. 搜索模型
```bash
ollama search deepseek-r1:8b
```

6. 查看帮助
```bash
ollama help
```