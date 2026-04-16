# tkzs_config_service

一个简单的配置中心，避免每个项目都需要手动自己配置.env的烦恼，在本地配置环境写死连接密码和公钥，在服务器启动一个go语言服务用于鉴权以及返回请求的对应文件(请求文件需要提前在服务器端配置好，可返回任意文件的内容，以文件的二进制内容返回)。Python客户端请求，从环境变量读取公钥和密码，请求对应接口获取对应.env配置到环境中

go的服务端代码在service中
src下为Python代码
服务端请自行部署。

# 安装

可以通过tkzs-config-service-client安装本服务

## 示例

```
uv安装uv add tkzs-config-service-client
pip安装pip install tkzs-config-service-client
```

# **版本兼容性提示(重要)**

> **请注意查看版本号，各v0.?.X客户端与服务器需要配套，v0.1.x与v0.2.X的服务器与客户端是不兼容升级。**
> **使用0.1.X的客户端请求0.2.X的服务端必然报错。使用0.2.X的客户端去请求0.1.X的服务端也必然报错**

