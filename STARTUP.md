# Identity Center 项目启动手册

## 一、更新项目代码
```bash
cd /home/zkjiao/usr/docker/identity-center
git pull origin main  # 替换为你的分支名
```

## 二、生成 Docker 镜像
```bash
# 确保已安装 Docker
sudo docker build -f docker/Dockerfile -t identity-center:local .
```

## 三、启动项目容器
```bash
# 使用 docker-compose 启动
cd docker
sudo docker compose up -d
```
容器会接入统一的 `app_net` 网络（external），与 `nginx1.30` 容器同网络，nginx 通过容器名即可反代。

## 四、Nginx 反代配置说明（统一Nginx容器）
### 1. 找到统一Nginx容器的配置目录
统一Nginx容器名为 `nginx1.30`，配置文件在 `/etc/nginx/conf.d/`
该目录是宿主机的 bind mount：`/home/zkjiao/usr/database/nginx/nginx1.30.3/conf.d/`，
直接修改宿主机文件即可，无需 docker exec 写入。

### 2. 创建反代配置文件
在宿主机 `/home/zkjiao/usr/database/nginx/nginx1.30.3/conf.d/identity-center.locations`
写入以下内容（利用 app_net 的内置 Docker DNS，用容器名访问，不经过宿主机端口）：
```nginx
location = /identity-center {
    return 301 /identity-center/;
}

location /identity-center/ {
    proxy_pass http://identity-center:8002/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
`default.conf` 中已有 `include /etc/nginx/conf.d/identity-center.locations;`，无需重复添加。

### 3. 重载Nginx配置
```bash
sudo docker exec nginx1.30 sh -c 'nginx -s reload'
```

### 4. 验证反代是否生效
访问 `http://119.45.48.180:8080/identity-center/health`，如果返回
`{"status":"ok","service":"identity-center"}`，说明反代配置成功。

## 附：查看服务状态
1. 检查容器运行状态：`sudo docker ps | grep identity-center`
2. 查看Nginx配置：`sudo docker exec nginx1.30 cat /etc/nginx/conf.d/default.conf`
3. 查看项目日志：`cd /home/zkjiao/usr/docker/identity-center && cat app.log`
