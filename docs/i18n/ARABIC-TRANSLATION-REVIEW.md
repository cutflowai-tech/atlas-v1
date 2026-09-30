# Atlas Arabic translation review

Generated from `src/atlas_commander/locales/catalog.json` (atlas-i18n-v1) by `python3 -m atlas_commander.i18n review`.
Do not edit by hand. Raw Monday values (Editor names, Video Types, statuses, labels, IDs) are never translated and are not listed.

678 keys: 149 Approved from brief, 362 Implemented conservatively, 167 Needs Arabic Review.

| Key | English | Arabic | Context | Status | Notes |
|---|---|---|---|---|---|
| `eta_issue.REQUESTED_ETA_SNAPSHOT_DIFFERS_FROM_LOG` | Requested ETA differs between the item and its history | Requested ETA الحالي يختلف عن المسجل في سجل التغييرات | Why a deadline is not classified | Needs Arabic Review | Check wording of 'history' (سجل التغييرات). |
| `meta.editors` | one: {n} Editor / other: {n} Editors | zero: {n} مونتير / one: مونتير واحد / two: {n} مونتير / two_gen: {n} مونتير / few: {n} مونتيرين / many: {n} مونتيرًا / other: {n} مونتير | Dashboard header chip | Needs Arabic Review | Brief gives '2 مونتير' for the header chip; other counts need confirmation. |
| `note.overall` | No overall performance status rule is approved for Atlas V1. The Editor's picture is the speed, deadline and quality sections below, each with its own sample size and Monday evidence. | لا توجد قاعدة معتمدة للتقييم العام للأداء في Atlas V1. صورة أداء المونتير هي نتائج السرعة والالتزام بمواعيد التسليم والجودة كلٌّ على حدة، مع أدلتها. | Profile note (overall) | Needs Arabic Review | English is the profile's note verbatim; confirm the Arabic summary is equivalent. |
| `noun.classified_delivery` | one: {n} classified delivery / other: {n} classified deliveries | zero: {n} عملية تسليم مصنفة / one: عملية تسليم واحدة مصنفة / two: عمليتا تسليم مصنفتان / two_gen: عمليتي تسليم مصنفتين / few: {n} عمليات تسليم مصنفة / many: {n} عملية تسليم مصنفة / other: {n} عملية تسليم مصنفة | Editor card headline | Needs Arabic Review | Dual forms (عمليتا/عمليتي) are formal; confirm the preferred register. |
| `noun.editor` | one: {n} Editor / other: {n} Editors | zero: {n} مونتير / one: مونتير واحد / two: مونتيران / two_gen: مونتيرين / few: {n} مونتيرين / many: {n} مونتيرًا / other: {n} مونتير | Counted Editors (sample sizes) | Needs Arabic Review | Brief uses مونتيران for 2; confirm few (3–10) = مونتيرين and many (11–99) = مونتيرًا. |
| `noun.issue_signal` | one: {n} issue signal / other: {n} issue signals | zero: {n} مؤشر مشكلات / one: مؤشر مشكلة واحد / two: مؤشرا مشكلات / two_gen: مؤشري مشكلات / few: {n} مؤشرات مشكلات / many: {n} مؤشرًا للمشكلات / other: {n} مؤشر مشكلات | Counted issue signals | Needs Arabic Review | Brief: 3 مؤشرات مشكلات. Dual and 11+ forms need confirmation. |
| `ops.current_publication` | Current publication | الإصدار المنشور حاليًا | Build-time operational status section | Needs Arabic Review | Confirm terminology for the live atomic publication. |
| `ops.failure_category` | Safe failure category | فئة الفشل الآمنة | Sync attempt field; never raw exception text | Needs Arabic Review | Technical operator wording; category value remains untranslated. |
| `ops.freshness_state.stale` | Stale | قديمة وغير محدثة | Data freshness state | Needs Arabic Review | Confirm preferred operational term for stale data. |
| `ops.scope_note.build_time` | This status was captured when this dashboard build was generated. The Atlas status CLI is authoritative for current runtime status. | تم تسجيل هذه الحالة وقت إنشاء هذا الإصدار من لوحة المتابعة. أمر حالة Atlas هو المرجع المعتمد للحالة التشغيلية الحالية. | Static dashboard operational-status scope explanation | Needs Arabic Review | Makes the distinction between static build context and authoritative current CLI status explicit. |
| `ops.scope_note.runtime` | This is current runtime context from the injected snapshot. | هذه هي الحالة التشغيلية الحالية وفقًا للّقطة المضمّنة. | Runtime operational-status scope explanation | Needs Arabic Review | Reserved for consumers that render an authoritative runtime snapshot. |
| `ops.scope_note.unknown` | The snapshot scope is unknown; do not treat this as current runtime status. | نطاق هذه اللقطة غير معروف؛ لا تتعامل معها باعتبارها الحالة التشغيلية الحالية. | Operational-status scope safety explanation | Needs Arabic Review | Fails safe when an older producer omits snapshot_scope. |
| `ops.snapshot_context` | Snapshot scope: {scope}. Generated {date}. | نطاق اللقطة: {scope}. وقت الإنشاء: {date}. | Operational-status snapshot provenance | Needs Arabic Review | The language-neutral scope code remains available in data-status-value. |
| `ops.snapshot_scope.build_time` | Build-time snapshot | لقطة وقت الإنشاء | Operational-status snapshot scope | Needs Arabic Review | Static context embedded while the dashboard build is generated. |
| `ops.snapshot_scope.runtime` | Runtime snapshot | لقطة وقت التشغيل | Operational-status snapshot scope | Needs Arabic Review | Current context supplied by an authoritative runtime consumer. |
| `ops.source_run` | Source run | تشغيل المصدر | Current publication and sync attempt field | Needs Arabic Review | Technical operator term; source run ID remains untranslated. |
| `ops.stale_after` | Stale after (seconds) | تُعد قديمة بعد (بالثواني) | Freshness configuration field | Needs Arabic Review | Confirm concise threshold wording. |
| `ops.system_state.degraded` | Degraded | متأثرة | System integrity state | Needs Arabic Review | Confirm terminology for usable but operationally degraded. |
| `ops.unavailable` | No operational status snapshot was injected for this build. This page does not infer system health from whether the HTML loaded. | لم يتم تضمين ملخص للحالة التشغيلية في هذا الإصدار. ولا تستنتج هذه الصفحة سلامة النظام من مجرد نجاح تحميلها. | Shown when the optional build-time status snapshot is absent | Needs Arabic Review | Safety wording: absence must never appear healthy. |
| `pending.overall_score.label` | Overall score | الدرجة العامة | Unapproved management rule (Data & System) | Needs Arabic Review |  |
| `pending.overall_score.reason` | Atlas V1 has no approved scoring; speed, deadline and quality stay separate with their own evidence. | لا يوجد في Atlas V1 أي نظام درجات معتمد؛ تبقى السرعة والالتزام بمواعيد التسليم والجودة منفصلة ولكل منها أدلتها. | Why the rule is not evaluated | Needs Arabic Review |  |
| `system.contract` | Executable contract | إصدار العقد التنفيذي | Field | Needs Arabic Review | Technical term for the versioned Monday contract; confirm wording. |
| `system.dashboard_document` | Dashboard document | إصدار مستند لوحة المتابعة | Field | Needs Arabic Review | Confirm 'لوحة المتابعة' for Dashboard. |
| `ui.back` | All Editors | كل المونتيرين | Back link from an Editor Profile to the overview | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.calculated` | Calculated | وقت الحساب | Drawer row: calculation time | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.card.sample` | {n} in window · {active} active | {n} في الفترة · {active} نشطة | Editor card subtitle: projects in the current window and Active Work count | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.change.short` | Recent change | التغيّر الأخير | Profile section bar: Recent Change | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.change.sub` | Current window {window} against {cwindow}. Facts only; no judgement without an approved rule. | الفترة الحالية {window} مقارنةً بالفترة {cwindow}. حقائق فقط؛ لا حكم دون قاعدة معتمدة. | Recent Change section subtitle with both windows | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.change.was` | before: {value} · n={n} | سابقًا: {value} · العدد={n} | Recent Change card: value in the comparison window | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.component_drawer_intro` | The state, the rule that produced it and every project it was calculated from. | الحالة، والقاعدة التي أنتجتها، وكل مشروع حُسبت منه. | Component evidence drawer introduction (HANDOFF-V2 §18) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.component_drawer_title` | {component} evidence · {name} | أدلة {component} · {name} | Drawer title for a component's evidence | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.data_status` | Data status and rules | حالة البيانات والقواعد | Tooltip of the data freshness link in the top bar | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.component` | Deadline component | مكوّن مواعيد التسليم | Deadline card heading with its state | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.early` | early · {n} projects | مبكر · {n} مشروع | Deadline stat: early share | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.fact` | Late {rate} ({late} of {n}) | متأخر {rate} ({late} من أصل {n}) | Deadline fact: absolute late rate with counts | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.late` | late · {n} projects | متأخر · {n} مشروع | Deadline stat: late share | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.on_time` | on time (exactly at ETA) · {n} projects | في الموعد (عند الموعد تمامًا) · {n} مشروع | Deadline stat: on-time share; no tolerance | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.deadline.unclassified` | {n} not classified ({no_time} ETA without a time, {no_eta} no ETA). | {n} غير مصنّف ({no_time} موعد دون وقت، {no_eta} دون موعد). | Deadline: unclassified projects and why (never guessed) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.evidence.coverage` | Data coverage | تغطية البيانات | Profile data coverage card (HANDOFF-V2 #26) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.evidence.excluded_window` | excluded in the current window | مستبعدة في الفترة الحالية | Coverage stat: projects excluded in the window | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.evidence.title` | Data & evidence | البيانات والأدلة | Profile evidence section heading | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.filter.all` | All | الكل | Status filter: no filter | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.filter.none` | Not classified | غير مصنّف | Status filter: Editors without an Overall Status (not enough evidence or approved logic) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.filter_label` | Filter by Overall Status | التصفية حسب الحالة العامة | Accessible label of the status filter group | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.history.short` | History | السجل | Profile section bar: history | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.history.title` | History | السجل | Profile history section heading | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.iv2.all` | {n} more published findings | {n} نتيجة منشورة أخرى | Summary of the collapsible list of published Intelligence findings below the Top findings on the Editors page; {n} excludes the Top findings and grouped duplicates (redesign T1.5). | Needs Arabic Review |  |
| `ui.iv2.block.execution_speed_competitive` | Execution speed is competitive under the approved Speed rule | سرعة التنفيذ منافسة وفق قاعدة السرعة المعتمدة | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.late_delivery_label_on_on_time_submission` | Late Delivery labels on on-time submissions | مؤشرات التأخير في التسليم على تسليمات تمت في الموعد | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.late_despite_typical_execution` | Late projects executed within the other Editors' typical time | مشاريع متأخرة نُفّذت خلال المدة المعتادة لبقية المونتيرين | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.late_projects_with_adequate_runway` | Late projects that had adequate runway | مشاريع متأخرة كانت مهلتها كافية | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.late_with_short_runway` | Late projects that started with short runway | مشاريع متأخرة بدأت بمهلة قصيرة | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.similar_historical_projects` | Similar historical projects | مشاريع تاريخية مماثلة | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.team_execution_moved_same_way` | The rest of the team's execution time moved the same way | مدة تنفيذ بقية الفريق تغيّرت في الاتجاه نفسه | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.team_late_rate_moved_same_way` | The rest of the team's late rate moved the same way | نسبة تأخير بقية الفريق تغيّرت في الاتجاه نفسه | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.team_negative_label_rate_moved_same_way` | The rest of the team's Negative label rate moved the same way | نسبة المؤشرات السلبية لبقية الفريق تغيّرت في الاتجاه نفسه | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.block.workload_by_period` | Workload in each period | عبء العمل في كل فترة | Intelligence evidence block description | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.data_warning` | Data warning | تنبيه بيانات | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.editor_specific_pattern` | Editor-specific pattern | نمط خاص بالمونتير | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.emerging_risk` | Emerging risk | خطر ناشئ | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.hidden_context` | Hidden context | سياق خفي | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.important_improvement` | Improvement | تحسّن | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.needs_attention` | Needs attention | يحتاج إلى انتباه | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.category.system_pattern` | System pattern | نمط على مستوى النظام | Intelligence finding category | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.cluster` | Closely overlapping findings grouped with this one | نتائج متداخلة مجمّعة مع هذه النتيجة | Finding drawer: duplicate cluster members (D53.14) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.confidence` | Confidence | قوة الأدلة | Finding card: confidence label (never a percentage) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.confidence_basis` | Why this confidence | أساس قوة الأدلة | Finding drawer: confidence factors heading | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.detector` | Detector {detector} · {version} | الكاشف {detector} · {version} | Finding drawer: detector and version (technical) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.editor_none` | No published finding includes this Editor for this snapshot. | لا توجد نتيجة منشورة تشمل هذا المونتير في هذه اللقطة. | Editor Profile: Intelligence empty state | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.editor_sub` | Findings that include this Editor, with their evidence and confidence. Context findings qualify the headline figures; they are not ratings. | النتائج التي تشمل هذا المونتير مع أدلتها وقوة أدلتها. نتائج السياق تقيّد الأرقام الرئيسية ولا تُعد تقييمات. | Editor Profile: Intelligence subtitle | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.editor_title` | Intelligence about this Editor | رؤى تحليلية عن هذا المونتير | Editor Profile: findings about the Editor | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.evidence_line` | {projects} · {editors} | {projects} · {editors} | Finding card: evidence size (projects and Editors) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.investigate` | Suggested investigation | التحقق المقترح | Finding card: the suggested next step | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.level.moderate` | Moderate | متوسطة | Confidence level | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.level.strong` | Strong | قوية | Confidence level | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.level.weak` | Weak | محدودة | Confidence level | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.limitations` | Limitations | حدود التحليل | Finding drawer: limitations heading | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.matters` | Why it matters | لماذا يهم | Finding card: management significance | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.meaning` | What it may mean | ما قد يعنيه ذلك | Finding card: the interpretation, labelled as interpretation | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.method` | Deterministic rules approved by management (D53). Findings describe what happened and what is associated with it, never a cause; every finding shows its Monday evidence. | قواعد حتمية اعتمدتها الإدارة (D53). تصف النتائج ما حدث وما يرتبط به، ولا تحدد سببًا أبدًا؛ وتعرض كل نتيجة أدلتها من Monday. | Intelligence method note | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.mixed` | The evidence is mixed. Evidence that qualifies this finding: | الأدلة متباينة. أدلة تقيّد هذه النتيجة: | Finding card: contradicting evidence shown next to the claim (D53.12) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.none` | No finding meets the approved evidence rules for this snapshot. | لا توجد نتيجة تستوفي قواعد الأدلة المعتمدة في هذه اللقطة. | Intelligence section empty state | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.noticed` | What Atlas noticed | ما لاحظه Atlas | Finding card: the observed facts | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.question` | Question for management | سؤال للإدارة | Finding drawer: investigation question | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.related` | +{n} related | +{n} مرتبطة | Finding card: clustered duplicate findings kept for audit | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.role.context` | Context | السياق | Finding drawer: evidence block role | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.role.contradicting` | Contradicting evidence | الأدلة المعاكسة | Finding drawer: evidence block role | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.role.supporting` | Supporting evidence | الأدلة الداعمة | Finding drawer: evidence block role | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.decision` | Decision | القرار | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.mode` | Mode | الوضع | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.not_evaluated` | Examined without a finding | فُحصت دون نتيجة | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.parameter` | Parameter | المعامل | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.published` | Published findings (all, including grouped duplicates) | النتائج المنشورة (كلها، بما فيها المكررة المجمّعة) | Data & rules: total number of findings in the published Intelligence document (redesign T1.5). | Needs Arabic Review |  |
| `ui.iv2.rules.scope` | On the Editors page | في صفحة المونتيرين | Data & rules: label of the row that splits the published total into what the Editors page shows (redesign T1.5). | Needs Arabic Review |  |
| `ui.iv2.rules.scope_value` | {top} top findings + {listed} more · {grouped} duplicates grouped under their main finding | {top} من أهم النتائج + {listed} أخرى · {grouped} مكررة مجمّعة تحت نتيجتها الرئيسية | Data & rules: value of the row that splits the published total (redesign T1.5). | Needs Arabic Review |  |
| `ui.iv2.rules.title` | Intelligence rules (D53) | قواعد الرؤى التحليلية (D53) | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.value` | Approved value | القيمة المعتمدة | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.version` | Intelligence version | إصدار الرؤى التحليلية | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.rules.withheld` | Weak signals kept for review | إشارات محدودة الأدلة محفوظة للمراجعة | Data & rules: Intelligence V2 rules card | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.scope` | Atlas published {total} findings: the {top} top findings above, these {listed}, and {grouped} duplicates grouped under their main finding (open a finding to see them). | نشر Atlas {total} نتيجة: أهم {top} نتائج أعلاه، وهذه النتائج الـ {listed}، و{grouped} نتائج مكررة مجمّعة تحت نتيجتها الرئيسية (افتح النتيجة لعرضها). | Note inside the list of published findings that reconciles its count with the total on Data & rules (ATLAS-DATA-002, redesign T1.5). | Needs Arabic Review |  |
| `ui.iv2.short` | Intelligence | رؤى تحليلية | Editor Profile section bar label | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.sub` | The most important evidence-backed findings, ranked. Atlas prefers silence over an unsupported conclusion. | أهم النتائج المدعومة بالأدلة، مرتبة حسب الأهمية. يفضّل Atlas الصمت على استنتاج غير مدعوم. | Intelligence section subtitle | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.title` | Intelligence | رؤى تحليلية | Editors overview: Intelligence V2 section heading | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.to_check` | To check | للتحقق | Finding drawer: the hypothesis, stated as something to check | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.top` | Top findings | أهم النتائج | Heading above the (at most five) top findings | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.iv2.withheld` | {n} weak exploratory signals are kept for review and are not published. | {n} إشارة استكشافية محدودة الأدلة محفوظة للمراجعة ولا تُنشر. | Count of weak findings withheld from publication (D53.11) | Needs Arabic Review | Intelligence V2 (D53), feat/atlas-intelligence-v2. |
| `ui.kpi.deadline` | late rate · {late} of {n} · other Editors {others} | نسبة التأخير · {late} من أصل {n} · المونتيرون الآخرون {others} | Profile key figure: Deadline, absolute and comparison | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.kpi.quality` | scored issue rate · positive {pos} · n={n} | نسبة المشكلات المحتسبة · الإيجابية {pos} · العدد={n} | Profile key figure: Quality | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.kpi.work` | In progress or in revision · {n} awaiting approval | قيد التنفيذ أو التعديل · {n} بانتظار الاعتماد | Profile key figure: Active Work and Awaiting Approval | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.labels_on_project` | Monday Performance labels | علامات الأداء في Monday | Project evidence: labels on this project (all classes) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.nav.editors` | Editors | المونتيرون | Top navigation: the Editors overview (HANDOFF-V2 §12) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.nav.system` | Data & rules | البيانات والقواعد | Top navigation: data freshness, rules and coverage | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.no_match` | No Editor matches this search or filter. | لا يوجد مونتير يطابق هذا البحث أو التصفية. | Overview empty state after search/filter | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.none_this_month` | None this month | لا شيء هذا الشهر | Empty state of a label class for the month | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.open_evidence` | Open evidence | عرض الأدلة | Link opening a component's evidence drawer | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.overview_note` | Cards are in alphabetical order. Filters narrow the list; Atlas never ranks Editors. | البطاقات مرتبة أبجديًا. عوامل التصفية تضيّق القائمة فقط؛ Atlas لا يرتّب المونتيرين حسب الأداء. | Overview: explains order and filtering (no leaderboard, HANDOFF-V2 §24) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.period` | Period | الفترة | Drawer row: date range used | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.presentation.order` | Editor cards are in alphabetical order and can be filtered by Overall Status; there is no ranking. | بطاقات المونتيرين مرتبة أبجديًا ويمكن تصفيتها حسب الحالة العامة؛ ولا يوجد ترتيب حسب الأداء. | Presentation note: card order | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.profile.sub` | Current window {window} · compared with {cwindow} · data updated {updated} | الفترة الحالية {window} · مقارنةً بالفترة {cwindow} · آخر تحديث للبيانات {updated} | Editor Profile header: the one time window used by every figure (HANDOFF-V2 #24) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.quality.component` | Quality component | مكوّن الجودة | Quality card heading with its state | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.quality.fact` | Issues {nrate} · positive {prate} · n={n} | المشكلات {nrate} · الإيجابية {prate} · العدد={n} | Editor card Quality line: scored negative and positive label rates with the sample | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.quality.negative_rate` | scored issue rate · {n} of {total} projects | نسبة المشكلات المحتسبة · {n} من أصل {total} مشروع | Quality stat: scored negative rate with denominator (HANDOFF-V2 #11) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.quality.positive_rate` | scored positive rate · {n} of {total} projects | نسبة المؤشرات الإيجابية المحتسبة · {n} من أصل {total} مشروع | Quality stat: scored positive rate with denominator | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.quality.sub` | From Monday Performance labels: one occurrence is one event, no severity weights. | من علامات الأداء في Monday: كل ظهور يُحتسب مرة واحدة، دون أوزان للشدة. | Quality section subtitle | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.release` | Release | الإصدار | Data & rules: publication identity row | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.revisions.projects` | projects with client revisions · of {total} completed | مشاريع بها تعديلات من العميل · من أصل {total} مكتمل | Revision stat with denominator | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.rule` | Rule | القاعدة | Drawer row: rule version and approval | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.rules.pending` | Not evaluated yet | لم يُقيَّم بعد | Data & rules: judgements without an approved rule | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.rules.title` | Rules in use | القواعد المطبّقة | Data & rules: approval state of each rule | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.search_label` | Search Editors | ابحث عن مونتير | Accessible label of the Editor search box | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.search_placeholder` | Search by name…  ( / ) | ابحث بالاسم…  ( / ) | Placeholder of the Editor search box; / is the keyboard shortcut | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.sections_label` | Profile sections | أقسام الملف | Accessible label of the sticky profile section bar | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.deadline` | Deadline {relative}: late {rate} vs {others} for other Editors | مواعيد التسليم {relative}: التأخير {rate} مقابل {others} لدى المونتيرين الآخرين | Signal: approved Deadline component state with both late rates | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.label` | {label} ×{n} · {projects} | {label} ×{n} · {projects} | Signal: a Monday label and how often it occurs | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.quality_negative` | Quality component is Negative | مكوّن الجودة سلبي | Signal: approved Quality state Negative | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.quality_positive` | Quality component is Positive | مكوّن الجودة إيجابي | Signal: approved Quality state Positive | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.speed_faster` | {pct} faster than other Editors in {labels} (n={n}) | أسرع بنسبة {pct} من المونتيرين الآخرين في {labels} (العدد={n}) | Signal: approved speed verdict Faster in one Video Type | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signal.speed_slower` | {pct} slower than other Editors in {labels} (n={n}) | أبطأ بنسبة {pct} من المونتيرين الآخرين في {labels} (العدد={n}) | Signal: approved speed verdict Slower in one Video Type (a comparison, not a judgement) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signals.good` | Positive signals | مؤشرات إيجابية | Profile signals column: positive facts | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signals.review` | Worth reviewing | تستحق المراجعة | Profile signals column: facts management may want to look at (never a judgement of the person) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signals.short` | Signals | المؤشرات | Profile section bar: signals | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signals.sub` | Supported facts only, each with its evidence. These are not Strength or Attention ratings. | حقائق مدعومة بالبيانات فقط، ولكل منها أدلتها. هذه ليست تقييمات لنقاط القوة أو لما يحتاج إلى متابعة. | Profile signals subtitle: no unapproved judgement | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.signals.title` | Signals in the current window | المؤشرات في الفترة الحالية | Profile: supported facts grouped by direction | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.speed.component` | Speed component | مكوّن السرعة | Speed card heading with its state | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.speed.fact` | {labels}: {editor} vs {others} · n={n} | {labels}: {editor} مقابل {others} · العدد={n} | Speed fact: this Editor's median vs other Editors' median in one Video Type | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.speed.fact_alone` | {labels}: {editor} · n={n} · no comparison | {labels}: {editor} · العدد={n} · بلا مقارنة | Speed fact when no other Editor is in the Video Type | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.speed.note` | Each Video Type is compared only within itself; other Editors exclude this Editor. | تُقارن كل Video Type بنفسها فقط؛ والمونتيرون الآخرون لا يشملون هذا المونتير. | Speed section note: segmentation and leave-one-out | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.speed.sample` | n = {e} this Editor · {t} other Editors' projects · {editors} Editors | العدد = {e} لهذا المونتير · {t} مشروع للمونتيرين الآخرين · {editors} مونتير | Speed row sample sizes (HANDOFF-V2 #15) | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.team.labels` | Labels this month | العلامات هذا الشهر | Team context tab: label activity by class | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.team.labels_sub` | Monday Performance labels added in {period}, by class. | علامات الأداء في Monday التي أُضيفت في {period}، حسب الفئة. | Team labels tab subtitle | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.team.sub` | Shared context across the team. Secondary to each Editor's picture. | سياق مشترك على مستوى الفريق، وهو ثانوي مقارنة بصورة كل مونتير. | Overview: team context section subtitle | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.timeline.context_marker` | Context label: {label} | علامة سياق: {label} | Timeline marker description | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.timeline.legend_context` | Context label added | إضافة علامة سياق | Timeline legend | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.timeline.legend_positive` | Positive label added | إضافة علامة إيجابية | Timeline legend | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.timeline.positive_marker` | Positive label: {label} | علامة إيجابية: {label} | Timeline marker description | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `ui.v.avatar.ranked` | {name}, {tier}, rank {rank} of {of} | {name}، {tier}، الترتيب {rank} من {of} | Accessible name of a ranked Editor avatar: name, tier and rank among ranked Editors | Needs Arabic Review |  |
| `ui.v.avatar.tier` | {name}, {tier} | {name}، {tier} | Accessible name of an Editor avatar: name and tier | Needs Arabic Review |  |
| `ui.v.late.aria` | Late on {late_pct} of projects. | متأخر في {late_pct} من المشاريع. | Accessible name of the late-rate bar without counts | Needs Arabic Review |  |
| `ui.v.late.aria_count` | Late on {late_pct} of projects ({late} of {n}). | متأخر في {late_pct} من المشاريع ({late} من {n}). | Accessible name of the late-rate bar: the Editor's late rate and late projects of deadline-classifiable projects | Needs Arabic Review |  |
| `ui.v.late.none` | No deadline data this month | لا توجد بيانات مواعيد هذا الشهر | Late-rate bar when the Editor has no deadline-classifiable project in the window | Needs Arabic Review |  |
| `ui.v.late.team` | Team average {team_pct} | متوسط الفريق {team_pct} | Tooltip and accessible text of the team-average marker on the late-rate bar | Needs Arabic Review |  |
| `ui.v.tier.best` | Best | الأفضل | Redesign tier label (Best: top of the ranked Editors, no dimension worse than the team) | Needs Arabic Review |  |
| `ui.v.tier.low_activity` | Low activity | نشاط منخفض | Redesign tier label (Low activity: too few projects this window) | Needs Arabic Review |  |
| `ui.v.tier.steady` | Steady | مستقر | Redesign tier label (Steady: no concern, not outstanding) | Needs Arabic Review |  |
| `ui.v.tier.watch` | Watch | يحتاج متابعة | Redesign tier label (Watch: later or slower than the team, or overdue work) | Needs Arabic Review |  |
| `ui.v.tier.weakest` | Weakest | الأضعف | Redesign tier label (Weakest: far later than the team, or much slower and later) | Needs Arabic Review |  |
| `ui.work.sub` | Items by their current Monday status, as of {date}. | العناصر حسب حالتها الحالية في Monday، حتى {date}. | Current work section subtitle | Needs Arabic Review | Redesigned contract 1.5 UI (ui-ux branch). |
| `activity.empty_detail` | A missing label is not an assessment of quality. | غياب المؤشرات لا يُعد تقييمًا لجودة العمل. | Empty state detail | Implemented conservatively |  |
| `activity.empty_title` | No issue labels added this month | لم تتم إضافة أي مؤشرات مشكلات هذا الشهر | Empty state | Implemented conservatively |  |
| `activity.footer` | Factual counts, no severity weighting. Which activity needs attention is not evaluated yet. | أعداد فعلية بدون أوزان للخطورة. لم يتم بعد تقييم أي نشاط يحتاج للانتباه. | Card footnote | Implemented conservatively |  |
| `activity.sub` | Monday Performance Issues labels added in {period} | مؤشرات Performance Issues المضافة على Monday في {period} | Card subheading | Implemented conservatively |  |
| `activity.this_period` | this period | هذه الفترة | Fallback period | Implemented conservatively |  |
| `activity.title` | Issue activity | نشاط مؤشرات المشكلات | Card title | Implemented conservatively |  |
| `card.view_profile` | View profile | عرض ملف الأداء | Editor card link | Implemented conservatively |  |
| `common.by_month` | By month | حسب الشهر | Section heading | Implemented conservatively |  |
| `common.close` | Close | إغلاق | Drawer close button label | Implemented conservatively |  |
| `common.editor_median` | Editor median | وسيط المونتير | Median work duration of this Editor | Implemented conservatively |  |
| `common.more` | +{n} more | +{n} أخرى | More items not shown | Implemented conservatively |  |
| `common.no` | no | لا | Boolean value | Implemented conservatively |  |
| `common.none` | None | لا يوجد | Empty table/list | Implemented conservatively |  |
| `common.reason` | Reason | السبب | Table header | Implemented conservatively |  |
| `common.result` | Result | النتيجة | Speed comparison result | Implemented conservatively |  |
| `common.sample_n` | n={n} | العينة: {n} | Sample size (number of projects) | Implemented conservatively |  |
| `common.status` | Status | الحالة | Table header / comparison status | Implemented conservatively |  |
| `common.team` | Team | الفريق | Label for the team benchmark column | Implemented conservatively |  |
| `common.times` | ×{n} | ×{n} | Occurrence count chip | Implemented conservatively |  |
| `common.why` | Why | لماذا؟ | Link to an explanation | Implemented conservatively |  |
| `common.yes` | yes | نعم | Boolean value | Implemented conservatively |  |
| `conclusion.equal_to_team_median` | Equal to team median | مماثل لوسيط الفريق | Speed conclusion (describes the comparison, not the person) | Implemented conservatively |  |
| `conclusion.faster_than_team_median` | Faster than team median | أسرع من وسيط الفريق | Speed conclusion (describes the comparison, not the person) | Implemented conservatively |  |
| `conclusion.insufficient_sample` | Insufficient sample | حجم العينة غير كافٍ | Speed conclusion (describes the comparison, not the person) | Implemented conservatively |  |
| `conclusion.similar_to_team_median` | Similar to team median | مماثل لوسيط الفريق | Contract 1.5 speed conclusion (inclusive band) | Implemented conservatively |  |
| `conclusion.slower_than_team_median` | Slower than team median | أبطأ من وسيط الفريق | Speed conclusion (describes the comparison, not the person) | Implemented conservatively |  |
| `coverage.all_projects` | All projects | جميع المشاريع | Heading | Implemented conservatively |  |
| `coverage.completed` | Completed | مكتملة | Field / table header | Implemented conservatively |  |
| `coverage.drawer_title` | Projects · {name} | المشاريع · {name} | Drawer title | Implemented conservatively |  |
| `coverage.excluded` | Excluded from metrics | مستبعدة من المؤشرات | Heading | Implemented conservatively |  |
| `coverage.measurable` | Measurable for speed | قابلة لقياس السرعة | Field | Implemented conservatively |  |
| `coverage.open` | Open | مفتوحة | Field | Implemented conservatively |  |
| `deadline.classified` | Classified | مصنفة | Drawer field | Implemented conservatively |  |
| `deadline.data_notes` | Data notes | ملاحظات البيانات | Drawer heading | Implemented conservatively |  |
| `deadline.drawer_intro` | A delivery is classified only when its Requested ETA has a date and a time. Atlas never guesses a missing time. Delivery is compared with the ETA in effect at the first Ready For Approval; exactly at the ETA is on time. | يتم تصنيف التسليم فقط عندما يحتوي Requested ETA على تاريخ ووقت، ولا يخمّن Atlas أي وقت غير مسجل. تتم المقارنة مع Requested ETA المسجل عند أول Ready For Approval، والتسليم في نفس الموعد تمامًا يُعد في الموعد. | Drawer intro | Implemented conservatively |  |
| `deadline.drawer_title` | Deadline data · {name} | بيانات مواعيد التسليم · {name} | Drawer title | Implemented conservatively |  |
| `deadline.eta_without_time` | ETA without a time | Requested ETA بدون وقت | Drawer field | Implemented conservatively |  |
| `deadline.group.early` | Early projects | المشاريع المسلّمة مبكرًا | Button listing deliveries by result | Implemented conservatively |  |
| `deadline.group.late` | Late projects | المشاريع المسلّمة متأخرًا | Button listing deliveries by result | Implemented conservatively |  |
| `deadline.group.on_time` | On time projects | المشاريع المسلّمة في الموعد | Button listing deliveries by result | Implemented conservatively |  |
| `deadline.group_title.early` | Early deliveries · {name} | التسليمات المبكرة · {name} | Drawer title | Implemented conservatively |  |
| `deadline.group_title.late` | Late deliveries · {name} | التسليمات المتأخرة · {name} | Drawer title | Implemented conservatively |  |
| `deadline.group_title.on_time` | On time deliveries · {name} | التسليمات في الموعد · {name} | Drawer title | Implemented conservatively |  |
| `deadline.late_rate` | late {pct} | متأخر {pct} | Monthly row | Implemented conservatively |  |
| `deadline.no_eta` | No Requested ETA | لا يوجد Requested ETA | Drawer field | Implemented conservatively |  |
| `deadline.other_reasons` | Not evaluated for other reasons | لم يتم تقييمها لأسباب أخرى | Drawer field | Implemented conservatively |  |
| `deadline.strip_label` | {early} early, {on_time} on time, {late} late of {total} classified | {early} مبكر، {on_time} في الموعد، {late} متأخر — من أصل {total} مصنفة | Accessible label of the deadline bar | Implemented conservatively |  |
| `deadline.unavailable` | Deadline data unavailable | بيانات مواعيد التسليم غير متاحة | Empty state (not a judgement) | Implemented conservatively |  |
| `deadline.unavailable_detail` | No completed project has a Requested ETA with a time, so none can be classified. | لا يوجد مشروع مكتمل له Requested ETA يتضمن وقتًا، لذلك لا يمكن تصنيف أي مشروع. | Empty state detail | Implemented conservatively |  |
| `entry.open_dashboard` | Open the Atlas dashboard (English) | فتح لوحة متابعة Atlas (العربية) | Root and /en/, /ar/ entry pages | Implemented conservatively |  |
| `eta_issue.MISSING_REQUESTED_ETA` | No Requested ETA | لا يوجد Requested ETA | Why a deadline is not classified | Implemented conservatively |  |
| `eta_issue.NO_REQUESTED_ETA_AT_OR_BEFORE_READY_FOR_APPROVAL` | No Requested ETA was set by the first Ready For Approval | لم يتم تحديد Requested ETA حتى أول Ready For Approval | Why a deadline is not classified | Implemented conservatively |  |
| `eta_issue.REQUESTED_ETA_DATE_ONLY` | Requested ETA has a date but no time | Requested ETA يحتوي على تاريخ بدون وقت | Why a deadline is not classified | Implemented conservatively |  |
| `eta_issue.REQUESTED_ETA_INVALID` | Requested ETA could not be read | تعذّرت قراءة Requested ETA | Why a deadline is not classified | Implemented conservatively |  |
| `evidence.deadline_result` | {result} · {delta} against the Requested ETA | {result} · {delta} مقارنة بـ Requested ETA | Project evidence | Implemented conservatively |  |
| `evidence.deadline_unclassified` | {reason} — not classified | {reason} — غير مصنّف | Project evidence | Implemented conservatively |  |
| `evidence.eta_set_at` | (set {date}) | (تم تحديده {date}) | Project evidence | Implemented conservatively |  |
| `evidence.flags` | Flags: {flags} | علامات فنية: {flags} | Project evidence | Implemented conservatively |  |
| `evidence.included` | Included in metrics | مشمول في المؤشرات | Project evidence | Implemented conservatively |  |
| `evidence.included_lower` | included | مشمول | Report table cell | Implemented conservatively |  |
| `evidence.issues_heading` | Monday Performance Issues | Performance Issues على Monday | Project evidence heading | Implemented conservatively |  |
| `evidence.metric_status` | Metric status | حالة المؤشرات | Project evidence heading | Implemented conservatively |  |
| `evidence.monday_events` | Monday events | أحداث Monday | Project evidence heading | Implemented conservatively |  |
| `evidence.no_projects` | No projects. | لا توجد مشاريع. | Empty list | Implemented conservatively |  |
| `evidence.none_recorded` | None recorded | لا يوجد | Project evidence | Implemented conservatively |  |
| `evidence.not_used_for_speed` | not used for speed | غير مستخدم في قياس السرعة | Project evidence | Implemented conservatively |  |
| `evidence.open_project` | Open project evidence | عرض أدلة المشروع | Button | Implemented conservatively |  |
| `evidence.project_title` | Project {item} | مشروع {item} | Drawer title | Implemented conservatively |  |
| `evidence.revision_context` | {events} on this project. Context only — not a performance signal. | {events} على هذا المشروع. للسياق فقط — وليست مؤشرًا على الأداء. | Project evidence (revisions never imply fault) | Implemented conservatively |  |
| `fact.evidence_deadlines` | {n} deadlines classified: {early} early, {on_time} on time, {late} late. | تم تصنيف {n} من مواعيد التسليم: {early} مبكر، {on_time} في الموعد، {late} متأخر. | Snapshot fact | Implemented conservatively |  |
| `fact.evidence_projects` | {n} completed projects, {measurable} measurable for speed. | {completed}، منها {measurable} قابلة لقياس السرعة. | Snapshot fact | Implemented conservatively |  |
| `fact.issue_label` | {n} × {label} (Monday Performance Issues). | {n} × {label} (من Performance Issues في Monday). | Snapshot fact | Implemented conservatively |  |
| `fact.monthly_note` | Monthly figures are shown below with their sample sizes. | تظهر الأرقام الشهرية مع حجم العينة لكل شهر. | Snapshot fact | Implemented conservatively |  |
| `fact.workload` | {n} item(s) currently {status}. | {projects} حاليًا في حالة {status}. | Snapshot fact | Implemented conservatively |  |
| `field.label_added` | Label added | تاريخ إضافة المؤشر | Evidence field | Implemented conservatively |  |
| `field.monday_item` | Monday item | رقم المشروع على Monday | Evidence field | Implemented conservatively |  |
| `field.source` | Source | المصدر | Evidence field | Implemented conservatively |  |
| `field.work_duration` | Work duration | مدة العمل | Evidence field | Implemented conservatively |  |
| `field.work_started` | Work started | بداية العمل | Evidence field | Implemented conservatively |  |
| `hero.completed_small` | one: completed / other: completed | zero: مشروع مكتمل / one: مشروع مكتمل / two: مشروعان مكتملان / two_gen: مشروعين مكتملين / few: مشاريع مكتملة / many: مشروعًا مكتملًا / other: مشروع مكتمل | Words after the big completed-projects number | Implemented conservatively |  |
| `hero.level` | Level | مماثل | Card headline when equal to the team median | Implemented conservatively |  |
| `hero.level_big` | {big}{small} | {big} {small} | Card headline layout when equal | Implemented conservatively |  |
| `hero.level_small` | with team | لوسيط الفريق | Card headline when equal to the team median | Implemented conservatively |  |
| `hero.speed_big` | {pct}{word} | {word} {pct} | Card headline: percentage and direction word (order differs by language) | Implemented conservatively |  |
| `history.empty` | No monthly history in this snapshot | لا يوجد سجل شهري في هذه البيانات | Empty state | Implemented conservatively |  |
| `history.footer` | Trend not evaluated yet — months are shown side by side without an improving or declining label. Speed is per exact Video Type, never pooled. | لم يتم تقييم الاتجاه بعد — تُعرض الشهور جنبًا إلى جنب دون وصفها بالتحسن أو التراجع. السرعة محسوبة لكل Video Type على حدة ولا يتم دمج الأنواع. | Footnote | Implemented conservatively |  |
| `history.late_of` | · late {late} / {n} classified | · متأخر {late} من أصل {n} مصنفة | Monthly row | Implemented conservatively |  |
| `history.median_duration` | Median work duration | وسيط مدة العمل | Monthly row | Implemented conservatively |  |
| `history.no_data` | No data | لا توجد بيانات | Disabled month | Implemented conservatively |  |
| `history.no_deadlines` | No classified deadlines | لا توجد مواعيد تسليم مصنفة | Empty cell | Implemented conservatively |  |
| `history.no_figures` | No figures this month | لا توجد أرقام لهذا الشهر | Empty row | Implemented conservatively |  |
| `home.context_label` | Team context | سياق الفريق | Accessible section name | Implemented conservatively |  |
| `home.greeting.afternoon` | Good afternoon. | مساء الخير. | Time-of-day greeting replacing the heading | Implemented conservatively |  |
| `home.greeting.evening` | Good evening. | مساء الخير. | Time-of-day greeting replacing the heading | Implemented conservatively |  |
| `home.greeting.morning` | Good morning. | صباح الخير. | Time-of-day greeting replacing the heading | Implemented conservatively |  |
| `home.history_sub` | Month by month, most recent first. | شهرًا بشهر، من الأحدث إلى الأقدم. | Section subheading | Implemented conservatively |  |
| `home.history_title` | Performance History | سجل الأداء | Section heading | Implemented conservatively |  |
| `home.no_editors` | No Editor has attributable projects in this snapshot | لا يوجد مونتير لديه مشاريع قابلة للإسناد في هذه البيانات | Empty state | Implemented conservatively |  |
| `home.pulse_sub` | What happened, day by day. Select a marker for its evidence. | ما حدث يومًا بيوم. اختر أي علامة لعرض الأدلة الخاصة بها. | Section subheading | Implemented conservatively |  |
| `home.pulse_title` | Team Pulse | نبض الفريق | Section heading | Implemented conservatively |  |
| `home.team_sub` | Current performance evidence across the editing team. | أدلة الأداء الحالية لفريق المونتاج. | Section subheading | Implemented conservatively |  |
| `interp.all_history` | all history | كل السجل | Scope label for all-history counts (1.5 Overview card) | Implemented conservatively |  |
| `interp.card.components` | Q {quality} · S {speed} · D {deadline} | ج {quality} · س {speed} · م {deadline} | Compact component states on the Overview card | Implemented conservatively |  |
| `interp.component.overall_lookup` | Overall Status lookup table | جدول تحديد الحالة العامة | Why-this-status row | Implemented conservatively |  |
| `interp.coverage` | This Editor: {current} projects in the current window, {comparison} in the comparison window, {excluded} excluded | هذا المونتير: {current} مشروع في الفترة الحالية، و{comparison} في فترة المقارنة، و{excluded} مستبعد | Editor-scoped coverage | Implemented conservatively |  |
| `interp.deadline.absolute_note` | The absolute late rate is a fact. Doing better than the team comparison does not mean the lateness itself is acceptable. | نسبة التأخر الفعلية حقيقة ثابتة، والأداء الأفضل من مقارنة الفريق لا يعني أن التأخر نفسه مقبول. | D45/D46 | Implemented conservatively |  |
| `interp.deadline.comparator` | Other Editors: late rate {rate} · projects: {n} · Editors: {editors} | المونتيرون الآخرون: نسبة التأخر {rate} · المشاريع: {n} · المونتيرون: {editors} | D45 comparator | Implemented conservatively |  |
| `interp.deadline.dual` | Deadline: {relative} · Absolute late rate: {rate} ({late} of {n}) | الالتزام بالموعد: {relative} · نسبة التأخر الفعلية: {rate} ({late} من {n}) | D45 dual display | Implemented conservatively |  |
| `interp.deadline.relative.negative` | worse than team comparison | أسوأ من مقارنة الفريق | D45 | Implemented conservatively |  |
| `interp.deadline.relative.neutral` | similar to team comparison | مماثل لمقارنة الفريق | D45 | Implemented conservatively |  |
| `interp.deadline.relative.not_classifiable` | not classifiable | غير قابل للتصنيف | D45 | Implemented conservatively |  |
| `interp.deadline.relative.positive` | better than team comparison | أفضل من مقارنة الفريق | D45 | Implemented conservatively |  |
| `interp.direction.higher_is_better` | higher is better | الأعلى أفضل | Measure direction (D23) | Implemented conservatively |  |
| `interp.direction.lower_is_better` | lower is better | الأقل أفضل | Measure direction (D23) | Implemented conservatively |  |
| `interp.evidence.head.events` | Monday events | أحداث Monday | Evidence drill-down | Implemented conservatively |  |
| `interp.evidence.head.values` | Values used | القيم المستخدمة | Evidence drill-down | Implemented conservatively |  |
| `interp.evidence.show` | Evidence records | سجلات الأدلة | Evidence drill-down | Implemented conservatively |  |
| `interp.evidence.summary` | Evidence: {n} projects · rule {rule} · calculated {at} | الأدلة: {n} مشروع · القاعدة {rule} · حُسبت في {at} | Evidence summary | Implemented conservatively |  |
| `interp.facts_note` | Every component's facts are shown even when its rule is not approved yet; no classification is invented. | تُعرض حقائق كل مكوّن حتى إن لم تُعتمد قاعدته بعد؛ ولا يُختلق أي تصنيف. | D25/D47 note | Implemented conservatively |  |
| `interp.history_scope` | All completed projects · monthly history in Cairo months | جميع المشاريع المكتملة · السجل الشهري بأشهر توقيت القاهرة | Caption for all-history figures | Implemented conservatively |  |
| `interp.label.not_scored` | not scored | غير محتسبة | Evidence drill-down | Implemented conservatively |  |
| `interp.label.scored` | scored | محتسبة | Evidence drill-down | Implemented conservatively |  |
| `interp.measure.late_rate` | Late rate | نسبة التأخر | D40 measure | Implemented conservatively |  |
| `interp.measure.median_speed_seconds` | Median first-pass time | وسيط زمن الإنجاز الأول | D32 measure | Implemented conservatively |  |
| `interp.measure.negative_quality_rate` | Negative quality rate | معدل الجودة السلبي | D39 measure | Implemented conservatively |  |
| `interp.measure.positive_quality_rate` | Positive quality rate | معدل الجودة الإيجابي | D39 measure | Implemented conservatively |  |
| `interp.no_score` | Overall Status is a lookup of the Quality, Speed and Deadline states, with no score or weighting. Revisions, Current Work and context labels never affect it. | الحالة العامة تُحدَّد من جدول يربط حالات الجودة والسرعة والالتزام بالموعد، دون أي درجة أو أوزان. ولا تؤثر فيها التعديلات أو العمل الحالي أو علامات السياق. | D37 note | Implemented conservatively |  |
| `interp.pp` | {value} pp | {value} نقطة مئوية | Rate difference in percentage points | Implemented conservatively |  |
| `interp.quality.excluded` | Visible but not scored: {n} | ظاهرة وغير محتسبة: {n} | Quality exclusions (D27/D30) | Implemented conservatively |  |
| `interp.quality.facts` | Scored positive: {pos} ({prate}) · scored negative: {neg} ({nrate}) · eligible projects: {n} | إيجابية محتسبة: {pos} ({prate}) · سلبية محتسبة: {neg} ({nrate}) · مشاريع مؤهلة: {n} | Quality component facts (D39) | Implemented conservatively |  |
| `interp.reason.context_label` | context only | للسياق فقط | Label scoring exclusion (D26) | Implemented conservatively |  |
| `interp.reason.insufficient_comparator_editors` | too few other Editors to compare with | عدد المونتيرين الآخرين غير كافٍ للمقارنة | Classification reason (D36) | Implemented conservatively |  |
| `interp.reason.insufficient_sample` | not enough projects in the window | عدد المشاريع في الفترة غير كافٍ | Classification reason (D47) | Implemented conservatively |  |
| `interp.reason.lookup` | the approved lookup gives no status for this combination | لا يحدد الجدول المعتمد حالة لهذا التركيب | Classification reason (D37) | Implemented conservatively |  |
| `interp.reason.no_other_editors_in_cohort` | No valid team benchmark available | لا يتوفر مقياس فريق صالح للمقارنة | Classification reason (D35) | Implemented conservatively |  |
| `interp.reason.no_value_in_one_window` | no value in one of the two windows | لا توجد قيمة في إحدى الفترتين | Recent Change reason | Implemented conservatively |  |
| `interp.reason.not_enough_classifiable_components` | fewer than {min} of the 3 components are classifiable | أقل من {min} من المكوّنات الثلاثة قابلة للتصنيف | Classification reason (D41) | Implemented conservatively |  |
| `interp.reason.not_scored_quality` | visible, not scored in Quality | ظاهرة ولا تُحتسب في الجودة | Label scoring exclusion (D27/D30) | Implemented conservatively |  |
| `interp.reason.rule_not_approved` | rule not approved by management yet | لم تعتمد الإدارة القاعدة بعد | Classification reason (D25) | Implemented conservatively |  |
| `interp.recent.head.change` | Change | التغيّر | Recent Change table | Implemented conservatively |  |
| `interp.recent.head.comparison` | Comparison window | فترة المقارنة | Recent Change table | Implemented conservatively |  |
| `interp.recent.head.current` | Current window | الفترة الحالية | Recent Change table | Implemented conservatively |  |
| `interp.recent.head.measure` | Measure | المقياس | Recent Change table | Implemented conservatively |  |
| `interp.recent.head.trend` | Trend | الاتجاه | Recent Change table | Implemented conservatively |  |
| `interp.recent_sub` | Current window minus comparison window, per measure. A Trend label appears only under an approved rule. | الفرق بين الفترة الحالية وفترة المقارنة لكل مقياس. ولا يظهر وصف الاتجاه إلا بقاعدة معتمدة. | D23 | Implemented conservatively |  |
| `interp.recent_title` | Recent Change | التغيّر الأخير | D23 | Implemented conservatively |  |
| `interp.section_title` | Overall Status | الحالة العامة | 1.5 Overall Status section | Implemented conservatively |  |
| `interp.speed.comparator_value` | {median} · projects: {n} · Editors: {editors} | {median} · المشاريع: {n} · المونتيرون: {editors} | Speed comparator cell | Implemented conservatively |  |
| `interp.speed.facts` | Projects in classified Video Types: {n} | المشاريع في أنواع الفيديو المصنّفة: {n} | Speed component facts (D38) | Implemented conservatively |  |
| `interp.speed.head.comparator` | Other Editors | المونتيرون الآخرون | Speed table (leave-one-out, D36) | Implemented conservatively |  |
| `interp.speed.head.difference` | Difference | الفرق | Speed table | Implemented conservatively |  |
| `interp.speed.head.editor` | This Editor | هذا المونتير | Speed table | Implemented conservatively |  |
| `interp.speed.head.type` | Video Type | Video Type | Speed table | Implemented conservatively |  |
| `interp.speed.value` | {median} · projects: {n} | {median} · المشاريع: {n} | Speed cell | Implemented conservatively |  |
| `interp.state.approved` | Approved | معتمد | Rule state | Implemented conservatively |  |
| `interp.state.negative` | Negative | سلبي | Component state (D37) | Implemented conservatively |  |
| `interp.state.neutral` | Neutral | محايد | Component state (D37) | Implemented conservatively |  |
| `interp.state.not_classifiable` | Not classifiable | غير قابل للتصنيف | Component state (D37) | Implemented conservatively |  |
| `interp.state.positive` | Positive | إيجابي | Component state (D37) | Implemented conservatively |  |
| `interp.state.rule_not_approved` | Not approved yet | غير معتمد بعد | Rule state | Implemented conservatively |  |
| `interp.status.below_expectations` | Below Expectations | دون التوقعات | Overall Status label (D37) | Implemented conservatively |  |
| `interp.status.good` | Good | جيد | Overall Status label (D37) | Implemented conservatively |  |
| `interp.status.mixed` | Mixed | متباين | Overall Status label (D37) | Implemented conservatively |  |
| `interp.status.not_enough_approved_logic` | Not enough approved logic to classify | لا توجد قواعد معتمدة كافية للتصنيف | D25 state | Implemented conservatively |  |
| `interp.status.not_enough_evidence` | Not enough evidence to classify | لا تتوفر أدلة كافية للتصنيف | D41/D47 data state | Implemented conservatively |  |
| `interp.status.strong` | Strong | قوي | Overall Status label (D37) | Implemented conservatively |  |
| `interp.trend.Declining` | Declining | في تراجع | Trend label (D23) | Implemented conservatively |  |
| `interp.trend.Improving` | Improving | في تحسّن | Trend label (D23) | Implemented conservatively |  |
| `interp.trend.Stable` | Stable | مستقر | Trend label (D23) | Implemented conservatively |  |
| `interp.value_n` | {value} · n = {n} | {value} · العدد = {n} | Value with sample | Implemented conservatively |  |
| `interp.verdict.faster` | Faster | أسرع | Speed verdict (D38) | Implemented conservatively |  |
| `interp.verdict.not_classifiable` | Not classifiable | غير قابل للتصنيف | Speed verdict (D38) | Implemented conservatively |  |
| `interp.verdict.similar` | Similar | مماثل | Speed verdict (D38) | Implemented conservatively |  |
| `interp.verdict.slower` | Slower | أبطأ | Speed verdict (D38) | Implemented conservatively |  |
| `interp.why_title` | Why this status | سبب هذه الحالة | D37 | Implemented conservatively |  |
| `interp.window` | Current window: {start} – {end} (Cairo time), compared with {cstart} – {cend} | الفترة الحالية: {start} – {end} (بتوقيت القاهرة)، مقارنةً بالفترة {cstart} – {cend} | Evaluation windows (D24) | Implemented conservatively |  |
| `interp.window_short` | Current window {start} – {end} | الفترة الحالية {start} – {end} | Section caption for window-scoped figures (D24) | Implemented conservatively |  |
| `lang.switch_label` | View this page in Arabic | عرض هذه الصفحة باللغة الإنجليزية | Accessible label of the language switch | Implemented conservatively |  |
| `metric.issues_across` | across {projects} of {total} | في {projects} من أصل {total} | Metric card | Implemented conservatively |  |
| `metric.projects_detail` | completed · {measurable} measurable for speed | مكتملة · {measurable} قابلة لقياس السرعة | Metric card | Implemented conservatively |  |
| `metric.speed_level` | level with team {team} · n={n} | مماثل لوسيط الفريق ({team}) · حجم العينة: {projects} | Metric card | Implemented conservatively |  |
| `metric.speed_median` | {labels} median | وسيط {labels} | Metric card | Implemented conservatively |  |
| `nav.main_label` | Main navigation | القائمة الرئيسية | Accessible name of the main navigation | Implemented conservatively |  |
| `note.not_attributed` | Projects whose Editor is unverified, unrecorded at Ready For Approval, or changed during the work are not attributed to any Editor and so do not appear in this profile. | المشاريع التي لم يتم التحقق من المونتير الخاص بها، أو لم يُسجل المونتير فيها عند Ready For Approval، أو تغيّر أثناء العمل، لا تُسند إلى أي مونتير ولذلك لا تظهر في هذا الملف. | Profile note (attribution) | Implemented conservatively |  |
| `note.positive` | No approved positive quality signal exists in V1; For Bonus is context only and does not affect quality. | لا يوجد مؤشر جودة إيجابي معتمد في V1؛ وعلامة For Bonus للسياق فقط ولا تؤثر على الجودة. | Profile note (positive signals) | Implemented conservatively |  |
| `note.positive_v15` | Positive and context labels are shown from Monday as separate factual evidence. Deadline labels remain visible but do not affect the Quality component, and no automatic recognition or reward judgement is made. | تُعرض العلامات الإيجابية وعلامات السياق من Monday كأدلة واقعية منفصلة. وتظل علامات الموعد النهائي ظاهرة لكنها لا تؤثر في مكوّن الجودة، ولا ينتج عنها حكم تلقائي بالتقدير أو المكافأة. | Profile note (positive signals), contract 1.5 | Implemented conservatively |  |
| `note.trend` | Monthly figures (UTC month of Ready For Approval) with their sample sizes. Speed is shown only per exact benchmark-eligible Video Type cohort, never pooled across cohorts. No trend conclusion or judgement is drawn. | أرقام شهرية (حسب شهر Ready For Approval بتوقيت UTC) مع حجم العينة. تظهر السرعة فقط لكل Video Type مؤهل للمقارنة على حدة، ولا يتم دمج الأنواع. لا يتم استنتاج أي اتجاه أو حكم. | Profile note (trend) | Implemented conservatively |  |
| `note.trend_v15` | Monthly figures (Africa/Cairo month of Ready For Approval) over every completed project, with their sample sizes. Speed is shown only per exact benchmark-eligible Video Type cohort, never pooled across cohorts. No trend conclusion or judgement is drawn from these months. | أرقام شهرية (بحسب شهر Ready For Approval بتوقيت القاهرة) لجميع المشاريع المكتملة مع حجم العينة. تُعرض السرعة لكل مجموعة Video Type مؤهلة للمقارنة فقط ولا تُدمج المجموعات. ولا يُستخلص من هذه الأشهر أي استنتاج أو حكم على الاتجاه. | Contract 1.5 monthly history note (D24) | Implemented conservatively |  |
| `note.workload` | Descriptive only. Which statuses count as the Editor's active workload is not defined in V1, so no capacity judgement is made. | وصفي فقط. لم يتم في V1 تحديد الحالات التي تُحسب ضمن عبء العمل الفعلي للمونتير، لذلك لا يوجد أي حكم على الطاقة الاستيعابية. | Profile note (workload) | Implemented conservatively |  |
| `note.workload_v15` | Active Work includes only In Progress, Revisions and Internal Revisions. Ready For Approval is shown separately as Awaiting Approval. No capacity judgement is made. | يشمل العمل النشط فقط حالات In Progress وRevisions وInternal Revisions. وتظهر Ready For Approval منفصلة بصفتها بانتظار الاعتماد. لا يصدر أي حكم على الطاقة الاستيعابية. | Contract 1.5 current-work semantics | Implemented conservatively |  |
| `noun.client_revision_event` | one: {n} client revision event / other: {n} client revision events | zero: {n} تعديل من العميل / one: تعديل واحد من العميل / two: تعديلان من العميل / two_gen: تعديلين من العميل / few: {n} تعديلات من العميل / many: {n} تعديلًا من العميل / other: {n} تعديل من العميل | Counted client revisions (context only) | Implemented conservatively |  |
| `noun.later_eta_change` | one: {n} later Requested ETA change after Ready For Approval, ignored by the deadline rule. / other: {n} later Requested ETA changes after Ready For Approval, ignored by the deadline rule. | zero: {n} تغيير لاحق على Requested ETA بعد Ready For Approval، ولا تعتمد عليه قاعدة مواعيد التسليم. / one: تغيير واحد لاحق على Requested ETA بعد Ready For Approval، ولا تعتمد عليه قاعدة مواعيد التسليم. / two: تغييران لاحقان على Requested ETA بعد Ready For Approval، ولا تعتمد عليهما قاعدة مواعيد التسليم. / few: {n} تغييرات لاحقة على Requested ETA بعد Ready For Approval، ولا تعتمد عليها قاعدة مواعيد التسليم. / many: {n} تغييرًا لاحقًا على Requested ETA بعد Ready For Approval، ولا تعتمد عليها قاعدة مواعيد التسليم. / other: {n} تغيير لاحق على Requested ETA بعد Ready For Approval، ولا تعتمد عليه قاعدة مواعيد التسليم. | Project evidence note | Implemented conservatively |  |
| `ops.age_seconds` | Data age (seconds) | عمر البيانات (بالثواني) | Build-time operational status field | Implemented conservatively |  |
| `ops.attempt_id` | Attempt ID | معرّف محاولة المزامنة | Build-time operational status field | Implemented conservatively |  |
| `ops.attempt_state.running` | In progress | قيد التنفيذ | Sync attempt state | Implemented conservatively |  |
| `ops.board_id` | Monday board ID | معرّف لوحة Monday | Build-time operational status field | Implemented conservatively |  |
| `ops.completed_at` | Completed / failed at | وقت الاكتمال أو الفشل | Sync attempt field | Implemented conservatively |  |
| `ops.expected_interval` | Expected sync interval (seconds) | الفاصل المتوقع للمزامنة (بالثواني) | Freshness configuration field | Implemented conservatively |  |
| `ops.freshness_details` | Freshness thresholds | حدود حداثة البيانات | Build-time operational status section | Implemented conservatively |  |
| `ops.freshness_state.unknown` | Unknown | غير معروفة | Data freshness state | Implemented conservatively |  |
| `ops.publication_id` | Publication ID | معرّف الإصدار المنشور | Current publication field | Implemented conservatively |  |
| `ops.snapshot_scope.unknown` | Unknown scope | نطاق غير معروف | Operational-status snapshot scope | Implemented conservatively |  |
| `ops.started_at` | Started at | وقت البدء | Sync attempt field | Implemented conservatively |  |
| `ops.system_state.failed` | Failed | متعطلة | System integrity state | Implemented conservatively |  |
| `ops.system_state.healthy` | Healthy | سليمة | System integrity state | Implemented conservatively |  |
| `ops.system_state.unknown` | Unknown | غير معروفة | System integrity state | Implemented conservatively |  |
| `page.dashboard_title` | Atlas — Editing team | Atlas — فريق المونتاج | Browser tab title of the dashboard | Implemented conservatively |  |
| `patterns.empty_detail` | Atlas currently shows shared evidence without assigning a team-level cause. | يعرض Atlas حاليًا الأدلة المشتركة دون تحديد سبب على مستوى الفريق. | Empty state detail | Implemented conservatively |  |
| `patterns.empty_title` | Pattern detection is not active yet. | رصد الأنماط غير مفعّل حتى الآن. | Empty state | Implemented conservatively |  |
| `patterns.sub` | Across the editing team | على مستوى فريق المونتاج | Card subheading | Implemented conservatively |  |
| `patterns.title` | Team & process patterns | أنماط الفريق وسير العمل | Card title | Implemented conservatively |  |
| `pending.management_recommendation.label` | Management recommendation | توصية للإدارة | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.management_recommendation.reason` | Recommendations are outside Atlas V1 scope; AI may explain but is never the source of truth. | التوصيات خارج نطاق Atlas V1؛ يمكن للذكاء الاصطناعي أن يشرح لكنه لا يكون أبدًا مصدر الحقيقة. | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.needs_attention.label` | Needs attention | يحتاج للانتباه | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.needs_attention.reason` | No rule defines when an Editor needs management attention. | لا توجد قاعدة تحدد متى يحتاج المونتير إلى انتباه الإدارة. | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.overall_status.reason` | No overall performance status rule is approved for Atlas V1. | لا توجد قاعدة معتمدة للتقييم العام للأداء في Atlas V1. | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.positive_signals.label` | Positive signals | المؤشرات الإيجابية | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.positive_signals.reason` | No approved positive quality signal exists in V1; For Bonus is context only (D10). | لا يوجد مؤشر جودة إيجابي معتمد في V1؛ وعلامة For Bonus للسياق فقط (D10). | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.reward_recommendation.label` | Reward recommendation | توصية بالمكافأة | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.reward_recommendation.reason` | No reward rule is approved; For Bonus labels are context only (D10). | لا توجد قاعدة مكافآت معتمدة؛ وعلامات For Bonus للسياق فقط (D10). | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.team_patterns.label` | Team / process patterns | أنماط الفريق / سير العمل | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.team_patterns.reason` | No rule defines a team or process pattern; label counts per Editor are shown as facts only. | لا توجد قاعدة تحدد نمطًا على مستوى الفريق أو سير العمل؛ تُعرض أعداد المؤشرات لكل مونتير كحقائق فقط. | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.trend_direction.label` | Improving / declining | التحسن / التراجع | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.trend_direction.reason` | No trend rule is approved; monthly figures are shown with their sample sizes only. | لا توجد قاعدة معتمدة للاتجاه؛ تُعرض الأرقام الشهرية مع حجم العينة فقط. | Why the rule is not evaluated | Implemented conservatively |  |
| `pending.workload_capacity.label` | Workload / capacity judgement | الحكم على عبء العمل / الطاقة الاستيعابية | Unapproved management rule (Data & System) | Implemented conservatively |  |
| `pending.workload_capacity.reason` | Which current statuses count as active workload is an open decision (DECISIONS.md, open decision 5). | لم يتم بعد تحديد الحالات التي تُحسب ضمن عبء العمل الفعلي (DECISIONS.md، القرار المفتوح 5). | Why the rule is not evaluated | Implemented conservatively |  |
| `pending_v15.needs_attention.label` | Needs Attention Now | يحتاج إلى انتباه الآن | Glossary term (change-based, D-glossary); contract 1.5 | Implemented conservatively |  |
| `pending_v15.positive_signals.reason` | Positive Monday labels are shown as factual evidence; no Strength or Recognition threshold is approved. | تُعرض علامات Monday الإيجابية كأدلة واقعية؛ ولا توجد عتبة معتمدة لنقاط القوة أو التقدير. | Why the rule is not evaluated (contract 1.5) | Implemented conservatively |  |
| `pending_v15.reward_recommendation.reason` | No reward rule is approved; positive labels are evidence and never an automatic reward recommendation. | لا توجد قاعدة مكافآت معتمدة؛ فالعلامات الإيجابية أدلة وليست توصية تلقائية بالمكافأة. | Why the rule is not evaluated (contract 1.5) | Implemented conservatively |  |
| `pending_v15.trend_direction.reason` | Recent Change is shown as a fact with both windows and samples; no Trend materiality threshold is approved. | يُعرض التغيّر الأخير كحقيقة مع الفترتين وحجم العينة؛ ولا توجد عتبة معتمدة لأهمية تغيّر الاتجاه. | Why the rule is not evaluated (contract 1.5) | Implemented conservatively |  |
| `pending_v15.workload_capacity.reason` | Active Work statuses are approved; no capacity threshold or capacity judgement is approved. | حالات العمل النشط معتمدة؛ ولا توجد عتبة سعة أو حكم سعة معتمد. | Why the rule is not evaluated (contract 1.5) | Implemented conservatively |  |
| `profile.data_updated` | Data updated | آخر تحديث للبيانات | Header fact | Implemented conservatively |  |
| `profile.period` | Period | الفترة | Header fact | Implemented conservatively |  |
| `profile.report_intro` | The full Editor Profile as produced by the Atlas engine, with every project, exclusion and Monday event ID. | ملف أداء المونتير الكامل كما أنتجه Atlas، مع كل مشروع وكل استبعاد وكل معرّف حدث على Monday. | Drawer intro | Implemented conservatively |  |
| `profile.suggested_action` | Suggested action | الإجراء المقترح | Heading | Implemented conservatively |  |
| `profile.suggested_action_detail` | Not available yet. Management actions will appear here once Atlas has approved rules for them. | غير متاح حاليًا. ستظهر إجراءات الإدارة هنا بعد اعتماد قواعدها في Atlas. | Empty state | Implemented conservatively |  |
| `publication.identity` | Release {release} · source snapshot {snapshot} | الإصدار {release} · لقطة المصدر {snapshot} | Visible publication and source snapshot identifiers | Implemented conservatively |  |
| `publication.release` | Release {release} | الإصدار {release} | Compact visible publication identifier | Implemented conservatively |  |
| `quality.context_none` | No context labels on these projects. | لا توجد علامات سياق على هذه المشاريع. | Contract 1.5 empty Context label list | Implemented conservatively |  |
| `quality.context_title` | Context labels | علامات السياق | Contract 1.5 Context label class (High Workload, Additional Revisions); visible, never scored | Implemented conservatively |  |
| `quality.for_bonus` | For Bonus labels on {projects} — shown as context, not as a signal. | علامات For Bonus على {projects} — تُعرض كسياق فقط وليست مؤشرًا. | Context note | Implemented conservatively |  |
| `quality.positive_detail` | Recognition signals will appear here once supported by evidence. | ستظهر مؤشرات التقدير هنا عندما تدعمها الأدلة. | Empty state detail (absence is not a negative judgement) | Implemented conservatively |  |
| `quality.positive_detail_v15` | No positive Monday labels on these projects. | لا توجد علامات Monday إيجابية على هذه المشاريع. | Contract 1.5 empty Positive label list | Implemented conservatively |  |
| `quality.source_column` | Monday Performance Issues column | عمود Performance Issues في Monday | Evidence source | Implemented conservatively |  |
| `report.back` | Back to the dashboard | العودة إلى لوحة المتابعة | Link | Implemented conservatively |  |
| `report.coverage_title` | Data coverage | تغطية البيانات | Heading | Implemented conservatively |  |
| `report.current_title` | Current items (as of {date}) | المشاريع الحالية (حتى {date}) | Heading | Implemented conservatively |  |
| `report.deadline_note_frozen` | First Ready For Approval compared with the Requested ETA in effect at that moment; later ETA changes (for example a revision round) are listed as evidence and never change the result. No tolerance: exactly at the ETA is on time. | تتم المقارنة بين أول Ready For Approval وموعد Requested ETA المسجل في ذلك الوقت؛ وأي تغييرات لاحقة على الموعد (مثل جولة تعديلات) تظهر كأدلة ولا تغيّر النتيجة. بدون هامش سماح: التسليم في نفس الموعد تمامًا يُعد في الموعد. | Deadline rule (contract 1.4.0) | Implemented conservatively |  |
| `report.deadline_note_latest` | Ready For Approval compared with the latest Requested ETA. No tolerance: exactly at the ETA is on time. | تتم المقارنة بين Ready For Approval وآخر Requested ETA. بدون هامش سماح: التسليم في نفس الموعد تمامًا يُعد في الموعد. | Deadline rule (contract 1.3.0) | Implemented conservatively |  |
| `report.head.cohort` | Video Type cohort | مجموعة المقارنة (Video Type) | Table header | Implemented conservatively | Avoids a literal translation of 'cohort'. |
| `report.head.cohort_short` | Cohort | مجموعة المقارنة | Table header | Implemented conservatively |  |
| `report.head.conclusion` | Conclusion | النتيجة | Table header | Implemented conservatively |  |
| `report.head.current_status` | Current status | الحالة الحالية | Table header | Implemented conservatively |  |
| `report.head.deadlines_evaluated` | Deadlines evaluated | مواعيد تسليم تم تقييمها | Table header | Implemented conservatively |  |
| `report.head.difference` | Difference | الفرق | Table header | Implemented conservatively |  |
| `report.head.duration` | Duration | المدة | Table header | Implemented conservatively |  |
| `report.head.early_rate` | Early rate | نسبة المبكر | Table header | Implemented conservatively |  |
| `report.head.events` | In Progress / RFA events | أحداث In Progress / Ready For Approval | Table header | Implemented conservatively |  |
| `report.head.item` | Item | المشروع | Table header | Implemented conservatively |  |
| `report.head.items` | Items | العدد | Table header | Implemented conservatively |  |
| `report.head.label` | Label | المؤشر | Table header | Implemented conservatively |  |
| `report.head.late_rate` | Late rate | نسبة المتأخر | Table header | Implemented conservatively |  |
| `report.head.median_duration` | Median duration | وسيط المدة | Table header | Implemented conservatively |  |
| `report.head.month` | Month | الشهر | Table header | Implemented conservatively |  |
| `report.head.occurrences` | Occurrences | مرات الظهور | Table header | Implemented conservatively |  |
| `report.head.typical_range` | Team typical range (P25–P75) | النطاق المعتاد للفريق (P25–P75) | Table header (descriptive, not a target) | Implemented conservatively |  |
| `report.identity` | Editor {editor_id} · Monday label {label} · mapping {mapping} · contract {contract} · data retrieved {retrieved} · generated {generated} | المونتير {editor_id} · علامة Monday {label} · إصدار الربط {mapping} · إصدار العقد {contract} · آخر جلب للبيانات {retrieved} · وقت إنشاء التقرير {generated} | Identity line (IDs and timestamps shown as recorded) | Implemented conservatively |  |
| `report.no_issue_labels` | No performance issue labels. | لا توجد مؤشرات مشكلات. | Empty table | Implemented conservatively |  |
| `report.overall_title` | Overall picture | الصورة العامة | Heading | Implemented conservatively |  |
| `report.page_title` | Atlas Editor Profile · {name} | ملف أداء المونتير · {name} — Atlas | Browser tab title | Implemented conservatively |  |
| `report.projects_title` | Projects and evidence | المشاريع والأدلة | Heading | Implemented conservatively |  |
| `report.quality_note` | Each Monday Performance Issues label counts once, with no severity weights. | كل علامة Performance Issues في Monday تُحسب مرة واحدة، بدون أوزان للخطورة. | Quality explanation | Implemented conservatively |  |
| `report.show_monthly` | Show monthly figures | عرض الأرقام الشهرية | Disclosure | Implemented conservatively |  |
| `report.show_projects` | Show all {n} projects with their Monday event IDs | عرض جميع المشاريع ({n}) مع معرّفات أحداثها على Monday | Disclosure | Implemented conservatively |  |
| `report.speed_note` | Work duration is elapsed time from the first In Progress to the first Ready For Approval. The team benchmark is the {stat} of every eligible Editor in the same exact Video Type cohort, including this Editor. A faster/slower conclusion needs at least {min} of this Editor's projects in the cohort and at least one other Editor. The typical range is descriptive only. | مدة العمل هي الوقت المنقضي من أول In Progress حتى أول Ready For Approval. معيار مقارنة الفريق هو {stat} لكل المونتيرين المؤهلين في نفس Video Type بالضبط، ومن بينهم هذا المونتير. يحتاج استنتاج أسرع/أبطأ إلى {min_projects} على الأقل لهذا المونتير في نفس Video Type ووجود مونتير آخر على الأقل. النطاق المعتاد وصفي فقط وليس هدفًا مطلوبًا. | Speed explanation | Implemented conservatively |  |
| `report.speed_title` | Speed by exact Video Type | السرعة حسب Video Type بالضبط | Heading | Implemented conservatively |  |
| `report.tile.early_deliveries` | early deliveries ({n}/{total}) | تسليمات مبكرة ({n} من أصل {total}) | Tile | Implemented conservatively |  |
| `report.tile.early_rate` | early · {pct} | مبكر · {pct} | Tile | Implemented conservatively |  |
| `report.tile.eta_without_time` | ETA without a time (not classified) | Requested ETA بدون وقت (غير مصنّف) | Tile | Implemented conservatively |  |
| `report.tile.for_bonus` | projects with For Bonus (context) | مشاريع عليها For Bonus (للسياق فقط) | Tile | Implemented conservatively |  |
| `report.tile.late_deliveries` | late deliveries ({n}/{total}) | تسليمات متأخرة ({n} من أصل {total}) | Tile | Implemented conservatively |  |
| `report.tile.late_rate` | late · {pct} | متأخر · {pct} | Tile | Implemented conservatively |  |
| `report.tile.measurable` | measurable for speed | قابلة لقياس السرعة | Tile | Implemented conservatively |  |
| `report.tile.median_margin` | median margin (negative = early) | وسيط الفارق (القيمة السالبة = مبكر) | Tile | Implemented conservatively |  |
| `report.tile.no_eta` | no ETA | بدون Requested ETA | Tile | Implemented conservatively |  |
| `report.tile.on_time_rate` | on time (exactly at ETA) · {pct} | في الموعد (في نفس الموعد تمامًا) · {pct} | Tile | Implemented conservatively |  |
| `report.tile.projects_with_issues` | projects with issues of {total} | مشاريع بها مؤشرات من أصل {total} | Tile | Implemented conservatively |  |
| `report.tile.projects_with_revisions` | projects with revisions of {total} | مشاريع بها تعديلات من أصل {total} | Tile | Implemented conservatively |  |
| `report.tile.revision_rate` | revision rate | نسبة المشاريع التي بها تعديلات | Tile | Implemented conservatively |  |
| `revisions.drawer_intro` | Projects where a client asked for changes. Their cause is not known. | مشاريع طلب فيها العميل تعديلات، وسبب التعديلات غير معروف. | Drawer intro | Implemented conservatively |  |
| `revisions.of_completed` | of {completed} | من أصل {completed} | Tile detail | Implemented conservatively |  |
| `snapshot.head.over_time` | Over time | على مدار الوقت | Snapshot card heading | Implemented conservatively |  |
| `speed.benchmark_is_descriptive` | Team figures are historical and descriptive — not a target or an SLA. | أرقام الفريق تاريخية ووصفية فقط — وليست هدفًا أو مستوى خدمة مطلوبًا. | Benchmark disclaimer in each Video Type drawer | Implemented conservatively |  |
| `speed.drawer_intro` | Work duration runs from the first In Progress to the first Ready For Approval. Each Video Type is compared only with the {stat} of every eligible Editor in the same exact Video Type (this Editor included). A comparison needs at least {min} of this Editor's projects and at least one other Editor. The team figure is a historical benchmark, not a target. | تُحسب مدة العمل من أول In Progress حتى أول Ready For Approval. تتم مقارنة كل Video Type فقط مع {stat} لكل المونتيرين المؤهلين في نفس Video Type بالضبط (ومن بينهم هذا المونتير). تحتاج المقارنة إلى {min_projects} على الأقل لهذا المونتير، ووجود مونتير آخر على الأقل. رقم الفريق معيار مقارنة تاريخي وليس هدفًا مطلوبًا. | Speed explanation drawer | Implemented conservatively |  |
| `speed.drawer_title` | Speed · {name} | السرعة · {name} | Drawer title | Implemented conservatively |  |
| `speed.editor_value` | {median} · n={n} | {median} · العينة: {n} | Editor median with sample size | Implemented conservatively |  |
| `speed.how_compared` | How speed is compared | كيف تتم مقارنة السرعة | Info button | Implemented conservatively |  |
| `speed.line` | {labels}: {editor} vs {team} | {labels}: {editor} مقابل {team} | Editor median vs team median in one Video Type | Implemented conservatively |  |
| `speed.more_comparable` | +{n} comparable | +{n} قابلة للمقارنة | More Video Types | Implemented conservatively |  |
| `speed.more_not_comparable` | +{n} not comparable | +{n} غير قابلة للمقارنة | More Video Types | Implemented conservatively |  |
| `speed.no_measurable` | No measurable projects. | لا توجد مشاريع قابلة للقياس. | Empty state | Implemented conservatively |  |
| `speed.no_measurable_title` | No measurable projects | لا توجد مشاريع قابلة للقياس | Empty state | Implemented conservatively |  |
| `speed.none_comparable` | No comparable Video Type yet | لا يوجد Video Type قابل للمقارنة حتى الآن | Empty state (not a judgement) | Implemented conservatively |  |
| `speed.panel.level` | {strong} with team median | {strong} لوسيط الفريق | Verdict sentence | Implemented conservatively |  |
| `speed.team_value` | {median} · n={n} | {median} · العينة: {n} | Team median with sample size | Implemented conservatively |  |
| `speed.typical_range` | Team typical range (P25–P75) | النطاق المعتاد للفريق (P25–P75) | Descriptive range, not a target | Implemented conservatively |  |
| `speed.verdict.level` | Level with the team median | مماثل لوسيط الفريق | Comparison in one Video Type | Implemented conservatively |  |
| `stat.median` | median | الوسيط | Benchmark statistic name | Implemented conservatively |  |
| `status.cohort_not_benchmark_eligible` | Video Type combination not approved for benchmarking | تركيبة Video Type غير معتمدة للمقارنة | Speed comparison status | Implemented conservatively |  |
| `status.comparable` | Comparable | قابلة للمقارنة | Speed comparison status | Implemented conservatively |  |
| `status.insufficient_comparator_editors` | Too few other Editors | عدد المونتيرين الآخرين غير كافٍ | Speed comparison status | Implemented conservatively |  |
| `status.insufficient_editor_sample` | Fewer than the minimum Editor projects | عدد مشاريع المونتير أقل من الحد الأدنى | Speed comparison status | Implemented conservatively |  |
| `status.insufficient_sample` | Not enough projects | عدد المشاريع غير كافٍ | Speed comparison status | Implemented conservatively |  |
| `status.minimum_sample_size_not_configured` | Minimum sample not configured | لم يتم تحديد الحد الأدنى لحجم العينة | Speed comparison status | Implemented conservatively |  |
| `status.rule_not_approved` | Rule not approved yet | القاعدة غير معتمدة بعد | Speed comparison status | Implemented conservatively |  |
| `system.attribution_text` | {attributed} of {completed} in this snapshot have a verified Editor. The others are not shown on any Editor; unverified labels stay quarantined until confirmed. | {attributed} من أصل {completed} في هذه البيانات لها مونتير تم التحقق منه. لا تظهر المشاريع الأخرى ضمن أي مونتير، وتبقى العلامات غير المؤكدة معزولة حتى يتم تأكيدها. | Coverage explanation | Implemented conservatively |  |
| `system.head.atlas_id` | Atlas ID | معرّف Atlas | Data & System table header | Implemented conservatively |  |
| `system.head.editor_n` | Editor n | عينة المونتير | Data & System table header | Implemented conservatively |  |
| `system.head.eligible` | Eligible | مؤهل | Data & System table header | Implemented conservatively |  |
| `system.head.field` | Field | البند | Data & System table header | Implemented conservatively |  |
| `system.head.mapping` | Mapping | إصدار الربط | Data & System table header | Implemented conservatively |  |
| `system.head.monday_label` | Monday label | علامة Monday | Data & System table header | Implemented conservatively |  |
| `system.head.note` | Note | الملاحظة | Data & System table header | Implemented conservatively |  |
| `system.head.profile` | Profile | إصدار الملف | Data & System table header | Implemented conservatively |  |
| `system.head.profile_field` | Profile field | حقل الملف | Data & System table header | Implemented conservatively |  |
| `system.head.reason_not_attributed` | Reason not attributed | سبب عدم الإسناد | Data & System table header | Implemented conservatively |  |
| `system.head.team_n` | Team n | عينة الفريق | Data & System table header | Implemented conservatively |  |
| `system.mapped_without` | Mapped Editors without attributable projects | مونتيرون مسجلون بدون مشاريع قابلة للإسناد | Card heading | Implemented conservatively |  |
| `system.presentation.headline` | Editor card headline: the first comparable Video Type speed result; otherwise deadlines if any are classified; otherwise the project count. A fixed display order, not a judgement. | العنوان الرئيسي لبطاقة المونتير: أول نتيجة سرعة قابلة للمقارنة في Video Type؛ وإلا فمواعيد التسليم إن وُجدت مصنفة؛ وإلا فعدد المشاريع. ترتيب عرض ثابت وليس حكمًا. | Presentation note | Implemented conservatively |  |
| `system.presentation.languages` | English and Arabic pages are rendered from the same data. Monday values (names, Video Types, statuses, labels, IDs) are shown exactly as recorded. Time always runs left (earlier) to right (later). | الصفحات العربية والإنجليزية مبنية على نفس البيانات. تظهر قيم Monday (الأسماء وVideo Type والحالات والعلامات والمعرّفات) كما هي مسجلة تمامًا. ويسير الخط الزمني دائمًا من اليسار (الأقدم) إلى اليمين (الأحدث). | Presentation note | Implemented conservatively |  |
| `system.presentation.months` | Month pills group dated facts by UTC calendar month. | تُجمّع أزرار الشهور الأحداث المؤرخة حسب الشهر الميلادي بتوقيت UTC. | Presentation note | Implemented conservatively |  |
| `system.presentation.months_v15` | Month pills group dated facts by Africa/Cairo calendar month (D24); timestamps are shown in UTC. | تُجمّع أزرار الشهور الأحداث المؤرخة حسب الشهر بتوقيت القاهرة (D24)؛ وتُعرض الأوقات بتوقيت UTC. | Presentation note, contract 1.5 | Implemented conservatively |  |
| `system.presentation.timeline` | Timelines place each project at its first Ready For Approval and each issue label at the time it was added. Revision events are not dated in the Editor Profile, so they appear only as context on each project. | تضع الخطوط الزمنية كل مشروع عند أول Ready For Approval، وكل مؤشر مشكلة عند وقت إضافته. أحداث التعديل غير مؤرخة في ملف المونتير، لذلك تظهر فقط كسياق داخل كل مشروع. | Presentation note | Implemented conservatively |  |
| `system.presentation_notes` | Presentation notes | ملاحظات العرض | Card heading | Implemented conservatively |  |
| `system.rule.deadlines` | rule {rule}: first Ready For Approval against the Requested ETA in effect at that moment; no tolerance; a date-only or missing ETA is never classified. | القاعدة {rule}: أول Ready For Approval مقارنة بموعد Requested ETA المسجل في ذلك الوقت؛ بدون هامش سماح؛ ولا يتم تصنيف Requested ETA الذي يحتوي على تاريخ فقط أو غير المسجل. | Rule summary | Implemented conservatively |  |
| `system.rule.quality` | Monday Performance Issues labels; 1 occurrence = 1 label; no severity weights. | علامات Performance Issues في Monday؛ كل ظهور يُحسب مرة واحدة؛ بدون أوزان للخطورة. | Rule summary | Implemented conservatively |  |
| `system.rule.revisions` | context only; never a performance signal. | للسياق فقط؛ ولا تُعد أبدًا مؤشرًا على الأداء. | Rule summary | Implemented conservatively |  |
| `system.rule.speed` | elapsed time from first In Progress to first Ready For Approval; compared with the {stat} of every eligible Editor in the same exact Video Type; a conclusion needs {min}+ Editor projects and another Editor. The team figure is a historical benchmark, not a target. | الوقت المنقضي من أول In Progress حتى أول Ready For Approval؛ تتم المقارنة مع {stat} لكل المونتيرين المؤهلين في نفس Video Type بالضبط؛ ويحتاج الاستنتاج إلى {min_projects} على الأقل للمونتير ووجود مونتير آخر. رقم الفريق معيار مقارنة تاريخي وليس هدفًا مطلوبًا. | Rule summary | Implemented conservatively |  |
| `timeline.delivery.early` | Early delivery | تسليم مبكر | Timeline marker label | Implemented conservatively |  |
| `timeline.delivery.late` | Late delivery | تسليم متأخر | Timeline marker label | Implemented conservatively |  |
| `timeline.delivery.on_time` | On time delivery | تسليم في الموعد | Timeline marker label | Implemented conservatively |  |
| `timeline.delivery.unclassified` | Delivery, deadline not classified | تسليم غير مصنّف من حيث الموعد | Timeline marker label | Implemented conservatively |  |
| `timeline.direction_note` | Time runs left (earlier) to right (later). | يسير الخط الزمني من اليسار (الأقدم) إلى اليمين (الأحدث). | Explains that time is not mirrored on RTL pages | Implemented conservatively |  |
| `timeline.events` | Events | الأحداث | Timeline lane label | Implemented conservatively |  |
| `timeline.issue_marker` | Issue label: {label} | مؤشر مشكلة: {label} | Timeline marker label | Implemented conservatively |  |
| `timeline.legend_issue` | Issue label added | إضافة مؤشر مشكلة | Legend | Implemented conservatively |  |
| `timeline.legend_note` | Each delivery is placed at its first Ready For Approval. Client revisions are shown as context inside each project. | يظهر كل تسليم عند أول وصول للمشروع إلى Ready For Approval. تظهر تعديلات العميل كسياق فقط داخل كل مشروع. | Legend note | Implemented conservatively |  |
| `timeline.marker_aria` | {name}: {label}, {date}, project {item} | {name}: {label}، {date}، مشروع {item} | Timeline marker accessible label | Implemented conservatively |  |
| `timeline.no_events` | No dated events in this snapshot | لا توجد أحداث مؤرخة في هذه البيانات | Empty timeline | Implemented conservatively |  |
| `timeline.no_events_month` | No dated events this month | لا توجد أحداث مؤرخة في هذا الشهر | Empty lane | Implemented conservatively |  |
| `timeline.tick` | {month} {day} | {day} {month} | Axis tick (day of month) | Implemented conservatively |  |
| `timeline.updated` | Updated | آخر تحديث | Axis marker for the data retrieval time | Implemented conservatively |  |
| `warning.deadline_not_classifiable` | {n} completed projects have no Requested ETA with a time and are not classified for deadline. | لم يتم تصنيف {completed} من حيث موعد التسليم لعدم وجود Requested ETA يتضمن وقتًا. | Data-confidence note | Implemented conservatively |  |
| `warning.no_speed_comparison` | No Video Type cohort allows a speed comparison with other Editors. | لا يوجد Video Type يسمح حاليًا بمقارنة السرعة مع مونتيرين آخرين. | Data-confidence note | Implemented conservatively |  |
| `warning.partial_month` | {month} is still in progress (data retrieved {retrieved}). | شهر {month} ما زال جاريًا (آخر جلب للبيانات {retrieved}). | Data-confidence note | Implemented conservatively |  |
| `warning.projects_excluded` | {n} attributed projects are excluded from metrics ({reasons}). | تم استبعاد {projects} من المؤشرات ({reasons}). | Data-confidence note | Implemented conservatively |  |
| `warning.small_sample` | Only {n} completed projects; the approved minimum for a speed conclusion is {min} per Video Type. | {completed} فقط؛ الحد الأدنى المعتمد لاستنتاج السرعة هو {min} لكل Video Type. | Data-confidence note | Implemented conservatively |  |
| `workload.active_work` | Active Work | العمل النشط | Count of In Progress, Client Revision and Internal Revision projects | Implemented conservatively |  |
| `workload.awaiting_approval` | Awaiting Approval | بانتظار الاعتماد | Ready For Approval projects, separate from Active Work | Implemented conservatively |  |
| `workload.footer` | Factual context. Capacity is not evaluated. | سياق فعلي فقط. لا يتم تقييم الطاقة الاستيعابية. | Card footnote | Implemented conservatively |  |
| `workload.none` | No current items | لا توجد مشاريع حالية | Empty state | Implemented conservatively |  |
| `workload.sub` | Items by their current Monday status | المشاريع حسب حالتها الحالية على Monday | Card subheading | Implemented conservatively |  |
| `card.positive` | Positive | المؤشرات الإيجابية | Editor card line | Approved from brief |  |
| `common.current_work` | Current work | العمل الحالي | Section label | Approved from brief |  |
| `common.deadlines` | Deadlines | مواعيد التسليم | Section label | Approved from brief |  |
| `common.editor` | Editor | المونتير | Label for the Editor | Approved from brief |  |
| `common.evidence` | Evidence | الأدلة | Section label | Approved from brief |  |
| `common.issue_signals` | Issue signals | مؤشرات المشكلات | Section label | Approved from brief |  |
| `common.month_in_progress` | in progress | الشهر جارٍ | Current, incomplete month | Approved from brief |  |
| `common.no_signal` | No supported signal yet | لا توجد مؤشرات مدعومة بالبيانات حتى الآن | Missing positive/other signal (never a judgement) | Approved from brief |  |
| `common.not_classified` | Not classified | غير مصنّف | Deadline not classifiable | Approved from brief |  |
| `common.not_classified_lower` | not classified | غير مصنّف | Project list deadline cell | Approved from brief |  |
| `common.not_evaluated` | Not evaluated yet | لم يتم تقييمه بعد | Empty state for unapproved judgements | Approved from brief |  |
| `common.projects` | Projects | المشاريع | Section label / table header | Approved from brief |  |
| `common.quality` | Quality | الجودة | Section label | Approved from brief |  |
| `common.revisions` | Revisions | التعديلات | Section label | Approved from brief |  |
| `common.speed` | Speed | السرعة | Section label | Approved from brief |  |
| `common.team_median` | Team median | وسيط الفريق | Historical team median (descriptive, not a target) | Approved from brief |  |
| `conclusion.not_comparable` | Not comparable | لا تتوفر مقارنة موثوقة | Speed conclusion (describes the comparison, not the person) | Approved from brief |  |
| `deadline.counts` | {early} early · {on_time} on time · {late} late | {early} مبكر · {on_time} في الموعد · {late} متأخر | Deadline counts | Approved from brief |  |
| `deadline.coverage_button` | Classification coverage | المشاريع القابلة للتصنيف | Info button | Approved from brief |  |
| `deadline.negative_note` | Negative = delivered before the Requested ETA. | القيمة السالبة تعني التسليم قبل Requested ETA. | Explanation | Approved from brief |  |
| `deadline.of_total` | of {n} | — من أصل {n} | Deadline counts total | Approved from brief |  |
| `deadline.panel_sub` | First Ready For Approval against the Requested ETA in effect at that moment. | تتم المقارنة بين أول وصول للمشروع إلى Ready For Approval وموعد Requested ETA المسجل في ذلك الوقت. | Subheading | Approved from brief |  |
| `deadline.panel_summary` | {classified} · median margin {margin}{unclassified} | {classified} · وسيط الفارق {margin}{unclassified} | Summary | Approved from brief |  |
| `deadline.panel_title` | Deadline performance | الالتزام بمواعيد التسليم | Heading | Approved from brief |  |
| `event.editor` | Editor | المونتير | Monday event ID label | Approved from brief |  |
| `event.in_progress` | In progress | In Progress | Monday event ID label | Approved from brief |  |
| `event.ready_for_approval` | Ready for approval | Ready For Approval | Monday event ID label | Approved from brief |  |
| `event.requested_eta` | Requested ETA | Requested ETA | Monday event ID label | Approved from brief |  |
| `event.video_type` | Video type | Video Type | Monday event ID label | Approved from brief |  |
| `fact.speed_faster` | Faster than the team median in {labels} ({n} projects). | أسرع من وسيط الفريق في {labels} — بناءً على {projects}. | Snapshot fact (about one comparison, not the person) | Approved from brief |  |
| `fact.speed_slower` | Slower than the team median in {labels} ({n} projects). | أبطأ من وسيط الفريق في {labels} — بناءً على {projects}. | Snapshot fact (about one comparison, not the person) | Approved from brief |  |
| `field.deadline` | Deadline | موعد التسليم | Evidence field | Approved from brief |  |
| `field.editor` | Editor | المونتير | Evidence field | Approved from brief |  |
| `field.ready_for_approval` | Ready For Approval | Ready For Approval | Evidence field (exact Monday status) | Approved from brief |  |
| `field.requested_eta` | Requested ETA | Requested ETA | Evidence field (exact Monday field) | Approved from brief |  |
| `field.video_type` | Video Type | Video Type | Evidence field (kept as the Monday column name) | Approved from brief |  |
| `focus.available` | Available now | متاح حاليًا | Management focus column | Approved from brief |  |
| `focus.available.current_work` | Current work | العمل الحالي | Chip | Approved from brief |  |
| `focus.available.deadlines` | Deadlines | مواعيد التسليم | Chip | Approved from brief |  |
| `focus.available.history` | Monthly history | السجل الشهري | Chip | Approved from brief |  |
| `focus.available.issues` | Issue signals | مؤشرات المشكلات | Chip | Approved from brief |  |
| `focus.available.speed` | Speed vs team | السرعة مقارنة بالفريق | Chip / metric card | Approved from brief |  |
| `focus.body` | one: Performance evidence for {n} Editor is available below. Attention, recognition and trend insights will appear here once Atlas has approved rules for them — until then, nothing here is a judgement. / other: Performance evidence for {n} Editors is available below. Attention, recognition and trend insights will appear here once Atlas has approved rules for them — until then, nothing here is a judgement. | zero: بيانات الأداء متاحة حاليًا للمونتيرين المعروضين. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. / two: بيانات الأداء متاحة حاليًا للمونتيرين المعروضين. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. / few: بيانات الأداء متاحة حاليًا للمونتيرين المعروضين. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. / many: بيانات الأداء متاحة حاليًا للمونتيرين المعروضين. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. / other: بيانات الأداء متاحة حاليًا للمونتيرين المعروضين. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. / one: بيانات الأداء متاحة حاليًا للمونتير المعروض. ستظهر مؤشرات الانتباه والتقدير والاتجاهات بعد اعتماد قواعدها في Atlas. وحتى ذلك الحين، لا تمثل البيانات المعروضة هنا حكمًا على الأداء. | Management focus text | Approved from brief | Singular form adapted for one Editor. |
| `focus.calibrating` | Calibrating | قيد الإعداد | Management focus column | Approved from brief |  |
| `focus.calibrating.attention` | Attention | نقاط تحتاج للانتباه | Chip | Approved from brief |  |
| `focus.calibrating.overall` | Overall status | التقييم العام | Chip | Approved from brief |  |
| `focus.calibrating.patterns` | Team patterns | أنماط الفريق | Chip | Approved from brief |  |
| `focus.calibrating.recognition` | Recognition | مؤشرات التقدير | Chip | Approved from brief |  |
| `focus.calibrating.trends` | Trends | الاتجاهات | Chip | Approved from brief |  |
| `focus.eyebrow` | Management focus | نظرة الإدارة | Management focus eyebrow | Approved from brief |  |
| `focus.how_atlas_evaluates` | How Atlas evaluates → | كيف يقيّم Atlas الأداء ← | Link to Data & System (arrow points forward in each reading direction) | Approved from brief |  |
| `focus.title` | Management insights are being calibrated. | مؤشرات الإدارة ما زالت قيد الإعداد. | Management focus heading | Approved from brief |  |
| `hero.editor_median` | Editor median | وسيط {name} | Card headline figure caption | Approved from brief |  |
| `hero.sample` | n = {e} Editor projects · {t} team projects · {editors} · {labels} only | حجم العينة: {e_projects} لـ{name} · {t_projects} للفريق · {editors} · {labels} فقط | Card sample sizes | Approved from brief |  |
| `hero.speed_eyebrow` | Speed · {labels} vs team median | السرعة · {labels} مقارنة بوسيط الفريق | Card headline eyebrow | Approved from brief |  |
| `hero.word.faster` | faster | أسرع بنسبة | Card headline word | Approved from brief |  |
| `hero.word.slower` | slower | أبطأ بنسبة | Card headline word | Approved from brief |  |
| `home.sub` | Here’s your editing team today. | ملخص أداء فريق المونتاج اليوم. | Dashboard subheading | Approved from brief |  |
| `home.team_title` | Editor Team | فريق المونتاج | Section heading | Approved from brief |  |
| `home.title` | Editing team overview | نظرة عامة على فريق المونتاج | Dashboard heading | Approved from brief |  |
| `home.updated` | Updated {date} | آخر تحديث {date} | Header chip | Approved from brief |  |
| `issue.summary` | {signals} on {projects} | {signals} في {projects} | Issue signals summary | Approved from brief | Brief: 3 مؤشرات مشكلات في مشروعين. |
| `lang.other_name` | العربية | English | Language switch text (always the other language's own name) | Approved from brief |  |
| `metric.speed_faster` | {pct} faster than team {team} · n={n} | أسرع بنسبة {pct} من وسيط الفريق ({team}) · حجم العينة: {projects} | Metric card | Approved from brief |  |
| `metric.speed_slower` | {pct} slower than team {team} · n={n} | أبطأ بنسبة {pct} من وسيط الفريق ({team}) · حجم العينة: {projects} | Metric card | Approved from brief |  |
| `nav.system` | Data & System | البيانات والنظام | Top navigation and page title | Approved from brief |  |
| `nav.team` | Editor team | فريق المونتاج | Top navigation and back link | Approved from brief |  |
| `note.revisions` | Revision activity is context only. It does not imply Editor fault and never affects any metric or conclusion. | للسياق فقط. وجود تعديلات من العميل لا يعني أن المونتير أخطأ، ولا يؤثر على أي من مؤشرات الأداء. | Profile note (revisions) | Approved from brief |  |
| `noun.classified_project` | one: {n} classified / other: {n} classified | zero: {n} مشروع مصنف / one: مشروع واحد مصنف / two: مشروعان مصنفان / two_gen: مشروعين مصنفين / few: {n} مشاريع مصنفة / many: {n} مشروعًا مصنفًا / other: {n} مشروع مصنف | Deadline-classified projects | Approved from brief | Brief: 5 مشاريع مصنفة. |
| `noun.completed_project` | one: {n} completed project / other: {n} completed projects | zero: {n} مشروع مكتمل / one: مشروع واحد مكتمل / two: مشروعان مكتملان / two_gen: مشروعين مكتملين / few: {n} مشاريع مكتملة / many: {n} مشروعًا مكتملًا / other: {n} مشروع مكتمل | Counted completed projects | Approved from brief | Brief: 7 مشاريع مكتملة. |
| `noun.project` | one: {n} project / other: {n} projects | zero: {n} مشروع / one: مشروع واحد / two: مشروعان / two_gen: مشروعين / few: {n} مشاريع / many: {n} مشروعًا / other: {n} مشروع | Counted projects | Approved from brief | Examples from the brief: 5 مشاريع, 10 مشاريع, في مشروعين, مشروعان. |
| `noun.unclassified_project` | one: {n} unclassified / other: {n} unclassified | zero: {n} مشروع غير مصنف / one: مشروع واحد غير مصنف / two: مشروعان غير مصنفين / two_gen: مشروعين غير مصنفين / few: {n} مشاريع غير مصنفة / many: {n} مشروعًا غير مصنف / other: {n} مشروع غير مصنف | Deadline-unclassified projects | Approved from brief | Brief: مشروعان غير مصنفين. |
| `ops.attempt_state.failed` | Failed | فشلت | Sync attempt state | Approved from brief |  |
| `ops.attempt_state.success` | Successful | ناجحة | Sync attempt state | Approved from brief |  |
| `ops.data_freshness` | Data freshness | حداثة البيانات | Operational status dimension | Approved from brief |  |
| `ops.evidence_coverage` | Evidence coverage | نطاق البيانات | Current publication field | Approved from brief |  |
| `ops.freshness_state.delayed` | Delayed | متأخرة | Data freshness state | Approved from brief |  |
| `ops.freshness_state.fresh` | Fresh | حديثة | Data freshness state | Approved from brief |  |
| `ops.last_attempt` | Last sync attempt | آخر محاولة مزامنة | Build-time operational status section | Approved from brief |  |
| `ops.last_success` | Last successful sync | آخر مزامنة ناجحة | Build-time operational status section | Approved from brief |  |
| `ops.monday_retrieved` | Monday data retrieved | وقت جلب بيانات Monday | Current publication field; freshness clock | Approved from brief |  |
| `ops.published_at` | Published at | وقت النشر | Current publication field | Approved from brief |  |
| `ops.system_status` | System status | حالة النظام | Operational status dimension | Approved from brief |  |
| `ops.title` | Data & System status | حالة البيانات والنظام | Build-time operational status card heading | Approved from brief |  |
| `overall.aria` | Overall: Not evaluated yet | التقييم العام: لم يتم تقييمه بعد | Accessible label | Approved from brief |  |
| `overall.label` | Overall | التقييم العام | Editor card / profile header | Approved from brief |  |
| `pending.overall_status.label` | Overall status | التقييم العام | Unapproved management rule (Data & System) | Approved from brief |  |
| `profile.evidence_select` | Select one for its Monday events. | اختر مشروعًا لعرض أحداثه المسجلة على Monday. | Subheading | Approved from brief |  |
| `profile.evidence_sub` | Every completed and open project attributed to {name}, most recent first. | جميع المشاريع المكتملة والمفتوحة المسندة إلى {name}، مرتبة من الأحدث إلى الأقدم. | Subheading | Approved from brief |  |
| `profile.report_button` | Complete evidence report | تقرير الأدلة الكامل | Button | Approved from brief |  |
| `profile.report_title` | Complete evidence report · {name} | تقرير الأدلة الكامل · {name} | Drawer title | Approved from brief |  |
| `profile.snapshot_sub` | Facts from the Atlas engine. Judgements appear once their rules are approved. | حقائق محسوبة بواسطة Atlas. ستظهر التقييمات بعد اعتماد القواعد الخاصة بها. | Subheading | Approved from brief |  |
| `profile.snapshot_title` | Snapshot | ملخص الأداء | Heading | Approved from brief |  |
| `profile.timeline_sub` | Deliveries and issue labels, in the order they happened. | عمليات التسليم ومؤشرات المشكلات مرتبة حسب وقت حدوثها. | Subheading | Approved from brief |  |
| `profile.timeline_title` | Performance timeline | الخط الزمني للأداء | Heading | Approved from brief |  |
| `quality.affected` | Affected projects: {affected} / {total} | المشاريع التي ظهرت بها مؤشرات: {affected} من أصل {total} | Summary | Approved from brief |  |
| `quality.drawer_title` | Issue signals · {name} | مؤشرات المشكلات · {name} | Drawer title | Approved from brief |  |
| `quality.empty_detail` | This is not an assessment of quality — only that no Monday label was added. | هذا لا يُعد تقييمًا لجودة العمل؛ بل يعني فقط أنه لم تتم إضافة أي Performance Issues لهذا المونتير على Monday. | Empty state detail | Approved from brief |  |
| `quality.intro` | From the Monday Performance Issues column. No severity weights, no inferred causes. | هذه المؤشرات مأخوذة من عمود Performance Issues في Monday. جميع مرات الظهور لها الوزن نفسه، ولا يستنتج Atlas أسبابًا غير موجودة في البيانات. | Quality explanation | Approved from brief |  |
| `quality.none_recorded` | No issue labels recorded | لم يتم تسجيل أي مؤشرات مشكلات | Empty state (not an assessment) | Approved from brief |  |
| `quality.none_recorded_sentence` | No issue labels recorded. | لم يتم تسجيل أي مؤشرات مشكلات. | Empty state (not an assessment) | Approved from brief |  |
| `quality.not_an_assessment` | This is not an assessment of quality. | هذا لا يُعد تقييمًا لجودة العمل. | Empty state detail | Approved from brief |  |
| `quality.panel_title` | Quality & performance signals | مؤشرات الجودة والأداء | Heading | Approved from brief |  |
| `quality.positive_title` | Positive signals | المؤشرات الإيجابية | Card heading | Approved from brief |  |
| `report.head.client_revisions` | Client revisions | تعديلات العميل | Table header | Approved from brief |  |
| `report.revisions_title` | Revisions (context only) | التعديلات (للسياق فقط) | Heading | Approved from brief |  |
| `report.tile.completed` | completed projects | المشاريع المكتملة | Tile | Approved from brief |  |
| `report.tile.issue_labels` | performance issue labels | مؤشرات المشكلات | Tile | Approved from brief |  |
| `report.tile.positive` | positive signals | المؤشرات الإيجابية | Tile | Approved from brief |  |
| `result.early` | Early | مبكر | Deadline result | Approved from brief |  |
| `result.late` | Late | متأخر | Deadline result (of a delivery vs its Requested ETA, never of a person) | Approved from brief |  |
| `result.on_time` | On time | في الموعد | Deadline result | Approved from brief |  |
| `revisions.client_events` | Client revision events | مرات تعديلات العميل | Tile | Approved from brief |  |
| `revisions.context_heading` | Client revision context | تعديلات العميل | Heading | Approved from brief |  |
| `revisions.disclaimer` | Context only. Revisions do not imply Editor fault and never affect any metric. | للسياق فقط. وجود تعديلات من العميل لا يعني أن المونتير أخطأ، ولا يؤثر على أي من مؤشرات الأداء. | Revision disclaimer (core rule) | Approved from brief |  |
| `revisions.drawer_title` | Client revision context · {name} | تعديلات العميل · {name} | Drawer title | Approved from brief |  |
| `revisions.internal_events` | Internal revision events | مرات التعديل الداخلي | Tile | Approved from brief |  |
| `revisions.projects_with` | Projects with client revisions | مشاريع بها تعديلات من العميل | Tile / button | Approved from brief |  |
| `snapshot.head.attention` | May need a look | نقاط تستحق المراجعة | Snapshot card heading | Approved from brief |  |
| `snapshot.head.doing_well` | Doing well | مؤشرات إيجابية | Snapshot card heading | Approved from brief |  |
| `snapshot.head.evidence` | Evidence | الأدلة | Snapshot card heading | Approved from brief |  |
| `snapshot.head.workload` | Current work | العمل الحالي | Snapshot card heading | Approved from brief |  |
| `speed.panel.faster` | {pct} faster | أسرع بنسبة {pct} | Bold part of the verdict | Approved from brief |  |
| `speed.panel.sample` | n = {e} Editor · {t} team projects | حجم العينة: {e_projects} للمونتير · {t_projects} للفريق | Sample sizes | Approved from brief |  |
| `speed.panel.slower` | {pct} slower | أبطأ بنسبة {pct} | Bold part of the verdict | Approved from brief |  |
| `speed.panel.sub` | Each Video Type is compared only within itself — never pooled. | تتم مقارنة كل Video Type بشكل مستقل، ولا يتم دمج أنواع مختلفة في مقارنة واحدة. | Profile tab subheading | Approved from brief |  |
| `speed.panel.than` | {strong} than team median | {strong} من وسيط الفريق | Verdict sentence | Approved from brief |  |
| `speed.panel.title` | Speed by Video Type | السرعة حسب Video Type | Profile tab heading | Approved from brief |  |
| `speed.verdict.faster` | {pct} faster than the team median | أسرع بنسبة {pct} من وسيط الفريق | Comparison in one Video Type | Approved from brief |  |
| `speed.verdict.slower` | {pct} slower than the team median | أبطأ بنسبة {pct} من وسيط الفريق | Comparison in one Video Type | Approved from brief |  |
| `status.no_other_editors_in_cohort` | No other Editor in this cohort | لا يوجد مونتير آخر ضمن مجموعة المقارنة. | Speed comparison status | Approved from brief |  |
| `system.approved_rules` | Approved rules in use | القواعد المعتمدة حاليًا | Card heading | Approved from brief |  |
| `system.attribution_title` | Editor attribution coverage | تغطية إسناد المشاريع للمونتيرين | Card heading | Approved from brief |  |
| `system.data_quality_notes` | Data-quality notes | ملاحظات جودة البيانات | Card heading | Approved from brief |  |
| `system.editors_identity` | Editors and identity | المونتيرون والهوية | Card heading | Approved from brief |  |
| `system.excluded` | Projects excluded from metrics | مشاريع مستبعدة من المؤشرات | Card heading | Approved from brief |  |
| `system.generated` | Generated | وقت إنشاء التقرير | Field | Approved from brief |  |
| `system.retrieved` | Monday data retrieved | آخر جلب للبيانات من Monday | Field | Approved from brief |  |
| `system.snapshot` | Snapshot | ملخص البيانات | Card heading | Approved from brief |  |
| `system.speed_eligibility` | Speed benchmark eligibility | أهلية المقارنة في السرعة | Card heading | Approved from brief |  |
| `system.sub` | Where every figure comes from, which rules apply, and what Atlas does not evaluate yet. | اعرف مصدر كل رقم، والقواعد المستخدمة في حسابه، وما لا يقوم Atlas بتقييمه حتى الآن. | Page subheading | Approved from brief |  |
| `system.window` | Activity window | فترة النشاط | Field | Approved from brief |  |
| `tab.deadlines` | Deadlines | مواعيد التسليم | Profile tab | Approved from brief |  |
| `tab.evidence` | Evidence | الأدلة | Profile tab | Approved from brief |  |
| `tab.overview` | Overview | نظرة عامة | Profile tab | Approved from brief |  |
| `tab.quality` | Quality | الجودة | Profile tab | Approved from brief |  |
| `tab.revisions` | Revisions | التعديلات | Profile tab | Approved from brief |  |
| `tab.speed` | Speed | السرعة | Profile tab | Approved from brief |  |
| `unit.hours` | {value}h | {value} ساعة | Duration in hours (one decimal; same number in both languages) | Approved from brief |  |
