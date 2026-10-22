# 企业 Agent Benchmark 档案风

用户于 2026-10-22 选定 [reference.png](reference.png)，作为 `/enterprise-agent-benchmark` 页面的视觉依据。研究站迁移时保留此视觉，以及原有完整元数据和公开文件边界。

## 排版与交互

- 近黑背景 `#10100f`、米白正文、琥珀色 `#ddb266`，细线分隔条目，方形加减号控制展开。
- 标题采用衬线字体，日期位于左侧时间轴；选中的卡片以琥珀色左边框和实心深色底区分。
- 九个业务标签直接排列在筛选栏，选中项加下划线。窄屏允许横向滑动，搜索与结果数量仍可见。
- 同时只展开一篇论文。详情中的一句话总结、完整摘要、版本与引用信息保留，PDF 按钮置于卡片底部。
- 手机将详情标签与正文改为单列，长作者列表、引用和链接自动换行。

图稿中的摘要经过缩写，实际页面保留现有完整摘要及说明，因此展开卡片会更高。论文数据、链接和发布日期未因本次改版而改变。

## 资产来源

| 资产 | 来源与用途 |
| --- | --- |
| `reference.png` | 用户选定的 ImageGen 图稿。原文件为 `exec-2f71d3eb-3617-4429-8483-c2ccd0ea9de9.png`，1487 × 1058。 |
| `web/public/research/archive-grain.webp` | 用 ImageGen 生成的细微黑纸颗粒，作为 512px CSS 平铺背景；生成提示词见下文。 |
| Noto Serif SC Variable 5.3.1 | `@fontsource-variable/noto-serif-sc` 随站点自托管；使用 Unicode 范围分块加载。许可证保存于 `web/public/research/OFL-Noto-Serif-SC.txt`。 |
| 搜索、文档、箭头、加减号 | 仓库原有 `@phosphor-icons/react` 图标。 |

正文英文字体优先 Times New Roman，中文使用 Noto Serif SC，并保留系统宋体回退。ImageGen 字形没有可直接提取的字体文件，实际页面以此字体组合接近图稿。

## 黑纸纹理生成记录

最终生成文件为 `exec-a1a4fa26-b7fd-4d08-928c-9036664e9d04.png`，使用内置 ImageGen 对第一轮纹理降低对比度，`transparent_background: false`。最终 WebP 只做格式编码，未增加装饰元素。提示词如下。

```text
Use case: lighting-weather, precise material texture adjustment.
Edit target: the attached black paper texture tile.
Change only its darkness and contrast: the current grain is much too bright and too contrasty. Make it about 75 percent quieter. The entire final tile must be centered around the exact near-black color RGB (16,16,15), hexadecimal #10100f, with grain values typically varying only 2 or 3 RGB code values up or down. Extremely subtle grain, almost indistinguishable from a plain near-black fill at first glance. In particular remove the grey, brown, and bright fiber flecks. No pixel highlights brighter than RGB (24,24,23). The surface should remain totally uniform in average tone everywhere.
Preserve the random isotropic microscopic dry-paper tooth, very faint and fine, as a seamlessly repeating CSS background tile. A single square flat texture only, prefer 512x512 output. Keep the same material across all edges, without a seam. No text, no logo, no objects, no gradient, no vignette, no blurry cloudy areas, no directional grain, no stripes, no frame, no border, no wrinkle or paper crease. No transparency.
```

此仓库仅迁入公开页面源码、完整研究条目 JSON、必要的背景纹理、备案图标及字体许可。每日论文不下载或归档 PDF；Benchmark 的中英文文件仍使用原 OSS 链接。
