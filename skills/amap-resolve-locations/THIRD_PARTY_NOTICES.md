# THIRD_PARTY_NOTICES.md · 第三方来源与许可证说明

## GCJ-02 偏移公式

`scripts/coordinate_transform.py` 中的 WGS84→GCJ-02 正向公式采用**公开逆向推导**的 GCJ-02 偏移算法（参数 a=6378245.0、ee=0.00669342162296594323）。该算法无官方规范，广泛流传于开源社区，代表性实现：

- [wandergis/coordtransform](https://github.com/wandergis/coordtransform)（MIT License）
- [googollee/eviltransform](https://github.com/googollee/eviltransform)（MIT License）

本项目按数学公式**独立实现**，未复制上述项目的源代码。按 MIT License 的署名要求，在此注明来源并保留其版权说明：

```
Copyright (c) wandergis/coordtransform contributors (MIT)
Copyright (c) googollee/eviltransform contributors (MIT)
```

GCJ-02→WGS84 逆向为本项目实现的残差迭代反算，与上述项目的一步近似不同。

## 参考样例（测试用，注明来源）

`tests/test_coordinate_transform.py` 中的独立参考样例来自：

- wandergis/coordtransform README 公开示例：wgs84(116.404, 39.915) → gcj02(116.41024449916938, 39.91640428150164)；
- mapchaxun.cn 对照页（https://www.mapchaxun.cn/wgs84-gcj02）：wgs84(116.391275, 39.907201) → gcj02(116.397516, 39.908602)。

回代通过只证明公式数值闭合，不证明真实位置精度。

## 高德开放平台

运行时通过高德 Web 服务 API 获取坐标数据，须遵守[高德服务条款](https://lbs.amap.com/pages/terms/)；本仓库不含高德的任何代码、数据或 Key。
