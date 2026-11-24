外部数据接进来时只做了类型检查，结果一个递归引用的结构把服务直接打崩：引用解析缺少循环检测，自引用 schema 会无限展开；布尔值被当作整数，真值可以混过整数校验；联合类型命中首个分支就返回，后续分支不再尝试；额外字段被默认放行，未声明字段进入对象；深度预算只统计对象层数，数组嵌套可以绕过；宽度预算按字符长度计算，而不是按元素个数；数值边界使用严格不等，端点值被错误拒绝；错误列表只返回第一次失败，后续路径错误全部丢失；总入口先校验后查预算，超大文档会先被展开；批量校验复用引用解析缓存，第二份文档沿用第一份结果。schema/guard.py 是核心，tests/test_guard.py 15个红。要修的是：按上面的顺序把 10 个缺陷逐个修掉。

运行方式
--------

在仓库根目录执行：

    python -m pytest tests -q

初始状态必须恰好是 15 failed，且 15 个失败全部来自 NotImplementedError；不能出现 collection error、import error 或 syntax error。实现 8 个桩后应为 15 passed。测试完全离线，不访问网络，不使用随机数，也不读取系统时间。

字段表
------

字段表：安全 / 漏洞检测与攻防 / Bugfix / Python 3, pytest / 无外部依赖

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 安全 |
| 子方向 | 漏洞检测与攻防 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

约束
----

tests 目录和 tests/test_guard.py 不可修改，评测以此文件为准。只能修改 src/schema/guard.py。

src/schema/guard.py 是唯一实现文件，恰好 8 个桩，初始全部 raise NotImplementedError。8 个函数依次为：

    parse_schema(text) -> dict
    resolve_ref(schema, ref) -> dict
    type_matches(value, type_name) -> bool
    validate(value, schema, path, budget) -> list
    check_budget(budget, depth, width) -> bool
    number_bounds(value, schema) -> bool
    validate_document(doc, schema, policy) -> dict
    schema_batch(docs, schema, policy) -> dict

实现只使用 Python 标准库。不要引入第三方运行时依赖，不要联网，不要读取系统时间，不要使用随机数。

src 布局与 pyproject
-------------------

    sec-schema-guard/
      README.md
      pyproject.toml
      src/
        schema/
          __init__.py
          guard.py
      tests/
        conftest.py
        test_guard.py

pyproject.toml 的 tool.pytest.ini_options 将 pythonpath 设置为 src，tests/conftest.py 也会把 src 插入模块搜索路径，因此测试可以直接导入 schema.guard。项目采用 src 布局，实现位于 src/schema，测试位于 tests，两者严格分离。

测试与缺陷对应
--------------

前 10 个测试分别对应题面的 10 个缺陷，后 5 个覆盖正确语义。

| 测试 | 覆盖点 |
| --- | --- |
| test_defect_01_ref_cycle_is_detected | resolve_ref 检测引用环并拒绝 |
| test_defect_02_boolean_is_not_an_integer | bool 不得匹配 integer 或 number |
| test_defect_03_union_tries_every_branch | anyOf 必须尝试所有分支 |
| test_defect_04_undeclared_property_is_rejected | 未声明字段默认拒绝 |
| test_defect_05_array_nesting_consumes_depth_budget | 数组层数计入深度预算 |
| test_defect_06_width_counts_elements_not_characters | 宽度按元素或属性个数计算 |
| test_defect_07_number_bounds_include_endpoints | minimum 与 maximum 包含端点 |
| test_defect_08_report_all_path_errors | 收集全部逐路径错误 |
| test_defect_09_budget_is_checked_before_validation | 总入口先做预算检查 |
| test_defect_10_batch_keeps_documents_independent | 批量校验各文档状态隔离 |
| test_valid_document_passes_without_errors | 合法文档通过且无错误，未知 schema 关键字被拒绝 |
| test_type_mismatch_reports_exact_path | 类型错误路径精确到字段 |
| test_boundary_values_are_accepted | 总入口接受端点值 |
| test_cyclic_schema_is_rejected_without_recursion_error | 自引用 schema 不栈溢出 |
| test_two_batches_match_individual_validations | 两批独立校验与单独校验一致 |

语义约定
--------

schema 使用 JSON 对象表示；parse_schema 接受 JSON 文本，递归拒绝任何未知关键字并抛出 ValueError。允许的关键字为 type、properties、required、additionalProperties、items、anyOf、$ref、definitions、minimum、maximum。

引用只支持本文件的 JSON Pointer，例如 #/definitions/node；引用链必须逐跳解析，出现环时 resolve_ref 和总入口抛出 ValueError，不能依赖 RecursionError 终止。节点同时包含 $ref 与 definitions 时，$ref 是校验入口，definitions 只作为引用表，解析后以引用目标继续校验。

type 取值为 object、array、string、integer、number、boolean、null。bool 是独立类型，不能匹配 integer 或 number；integer 不能接受 bool；number 接受 int 或 float，但同样拒绝 bool。

对象默认拒绝未声明字段，除非 additionalProperties 显式为 true；required 中缺失的字段必须报告路径。数组 items 作用于每个元素。

anyOf 只有在所有分支都失败时才算失败，不能因为第一个分支失败就返回错误。校验结果中的每个错误是包含 path、code、message 的字典，path 使用 $.field 与 $[index] 形式；type、additional_property、required、bounds、budget 是保留 code。

budget 形如 {"max_depth": 4, "max_width": 8}，根节点深度为 1，每个对象或数组层增加 1；宽度是当前对象的属性个数或当前数组的元素个数。超过上限即拒绝，等于上限仍允许。validate 在越限节点返回 budget 错误；validate_document 在正式校验之前先检查整份文档，预算超限时只返回根路径 $ 上的 budget 错误，不展开字段校验。

minimum 与 maximum 都是闭区间。number_bounds 对端点返回 True，越界返回 False；非数值返回 False。

validate_document 的返回结构恰好是 {"ok": bool, "errors": list}。schema_batch 的返回结构恰好是 {"results": list}，results 与输入 documents 一一对应且顺序不变；每份文档都使用独立的预算、引用解析与错误状态，不得复用上一份文档的结果。

评测只认 tests/test_guard.py 的断言。不要删除、跳过、改写或参数化测试，也不要用 xfail 或条件跳过。