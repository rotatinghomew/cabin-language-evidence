# 资料字典

旅程及对应版本为评估时须保留的业务分组，反馈翻译不改变原参与人。初审分歧需要班位再核实，有裁定时采用当时可见的裁定。替代提示按其场景和语言核实，符合关键指引要求才可用于该场景。

## `playbacks.json`

实际播出片段可被不同语言入口或产品场景使用。

| 字段 | 含义 |
| --- | --- |
| `play` | 实际播出号 |
| `journey` | 旅程标识 |
| `content` | 源提示内容标识 |
| `version` | 车辆内容版本 |
| `scene` | 服务场景 |
| `language` | 播出语言 |
| `day` | 行程日 |
| `key_instruction` | 是否关键指引 |
| `rendition` | 采用的实际译文标识 |

## `feedback.json`

同一反馈的翻译件不是独立观测。

| 字段 | 含义 |
| --- | --- |
| `feedback` | 留言标识 |
| `journey` | 旅程标识 |
| `play` | 关联播出 |
| `language` | 留言语言 |
| `text` | 留言说法 |
| `received` | 可见日期 |
| `translation_of` | 如果是翻译件则引用原留言，否则为空 |

## `labels.json`

双人标注和复核席的后续裁定分开保留。

| 字段 | 含义 |
| --- | --- |
| `feedback` | 留言标识 |
| `reviewer` | 判断人 |
| `labels` | 可同时出现的原因 |
| `date` | 判断可见日 |
| `kind` | 初审或裁定 |

## `review_slots.json`

同一复核席于一个日期可处理的复核数，关键提示须有相应资格。

| 字段 | 含义 |
| --- | --- |
| `slot` | 班位编号 |
| `reviewer` | 复核席 |
| `day` | 日期 |
| `languages` | 拥有本语种能力 |
| `capacity` | 可完成复核数 |
| `critical` | 有关键指引复核资格 |

## `release_policy.json`

内容运营登记的关键用途保护上限。

| 字段 | 含义 |
| --- | --- |
| `scene` | 应用场景 |
| `language` | 目标语言 |
| `min_trips` | 近期独立审核旅程支持量下限 |
| `max_miss` | 关键错因漏判比例上限 |
| `source_lang` | 源提示语言 |
| `fallback` | 可用的独立替代提示标识 |

## `overrides.json`

译文复用关系及运营已接受在指定场景提供的提示。

| 字段 | 含义 |
| --- | --- |
| `content` | 源内容 |
| `scene` | 场景 |
| `language` | 语言 |
| `version` | 版本 |
| `state` | 拟发布或在用 |
| `equivalent` | 可互认的源内容范围 |
| `day` | 安排日 |
