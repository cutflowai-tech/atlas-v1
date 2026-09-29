"""Arabic management language for Intelligence V2 findings: the same codes, params and keys as ``narrative`` (English).

Every table here has exactly the keys of its English counterpart, and every sentence carries exactly the same isolated Monday
values and numbers (tests compare them), so the two languages state the same facts. Terminology follows the reviewed catalogue
(``locales/catalog.json``): المونتير for Editor; Monday statuses, "Requested ETA" and "Video Type" stay as recorded; Western digits.

Review status: **Needs Arabic Review** (like every new ``ui.*`` catalogue string). The wording keeps the English uncertainty
standards: facts are stated with counts, associations are never causes, interpretations and hypotheses are marked as such.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from atlas_commander.i18n import plural_category
from atlas_commander.investigation.narrative import _checks, abs_pct, mon, num, pct, signed_pct

Params = Mapping[str, Any]
CODE = "ar"
REVIEW_STATUS = "Needs Arabic Review"

# Counted nouns always keep the numeral (the same number as the English sentence): forms by CLDR category.
NOUNS = {
    "project": {"few": "مشاريع", "many": "مشروعًا", "other": "مشروع"},
    "late project": {"few": "مشاريع متأخرة", "many": "مشروعًا متأخرًا", "other": "مشروع متأخر"},
    "open project": {"few": "مشاريع مفتوحة", "many": "مشروعًا مفتوحًا", "other": "مشروع مفتوح"},
    "Editor": {"few": "مونتيرين", "many": "مونتيرًا", "other": "مونتير"},
    "completed project": {"few": "مشاريع مكتملة", "many": "مشروعًا مكتملًا", "other": "مشروع مكتمل"},
    "attributed project": {"few": "مشاريع منسوبة", "many": "مشروعًا منسوبًا", "other": "مشروع منسوب"},
    "historical project": {"few": "مشاريع تاريخية", "many": "مشروعًا تاريخيًا", "other": "مشروع تاريخي"},
}


def count(n: int, noun: str) -> str:
    forms = NOUNS[noun]
    category = plural_category("ar", int(n))
    return f"{num(n)} {forms.get(category, forms['other'])}"


def pp(value: Any) -> str:
    return "غير متاح" if value is None else f"{num(f'{abs(float(value)) * 100:.0f}')} نقطة مئوية"


def hrs(value: Any) -> str:
    return "غير متاح" if value is None else f"{num(f'{float(value):.1f}')} ساعة"


def pct_(value: Any) -> str:
    return "غير متاح" if value is None else pct(value)


def _material(p: Params) -> str:
    if p.get("material_pct") is not None:
        return num(f"{p['material_pct']:.0f}%")
    return pp(p.get("material_difference"))


def who(params: Params) -> str:
    name = params.get("editor_name") or params.get("editor_id")
    return mon(name) if name else "المونتير"


def types(params: Params) -> str:
    label = params.get("cohort_label") or params.get("group_label") or params.get("cohort_key")
    return mon(label) if label else "هذا الـ Video Type"


OUTCOME_NAMES = {"late_delivery": "التسليمات المتأخرة", "negative_quality_label": "المؤشرات السلبية المحتسبة",
                 "not_late_delivery": "التسليمات غير المتأخرة", "positive_quality_label": "المؤشرات الإيجابية المحتسبة"}
MEASURE_NAMES = {"late_rate": "نسبة التأخير", "negative_label_rate": "نسبة المؤشرات السلبية المحتسبة", "median_execution": "وسيط مدة التنفيذ"}
AGAINST = {"comparison": "الـ 30 يومًا المكتملة السابقة", "history": "سجل المونتير السابق"}
AGAINST_TEAM = {"comparison": "الـ 30 يومًا المكتملة السابقة", "history": "سجل الفريق السابق"}
SIGNALS = {"past_eta": "تجاوزت بالفعل موعد Requested ETA الخاص بها",
           "short_remaining_runway": "لديها وقت متبقٍّ أقل مما يحتاجه التنفيذ المعتاد لنوع Video Type الخاص بها",
           "elapsed_beyond_typical": "قيد التنفيذ منذ مدة أطول من معظم المشاريع التاريخية المماثلة",
           "editor_workload_above_own_high_percentile": "تخص مونتيرين لديهم حاليًا مشاريع نشطة أخرى أكثر من المئين 75 لعبء عملهم التاريخي",
           "review_wait_beyond_typical": "تنتظر الاعتماد منذ مدة أطول من معظم المراجعات التاريخية"}
PHASES = {"pre_editor": "قبل المونتير", "editor_execution": "تنفيذ المونتير", "review_wait": "انتظار المراجعة",
          "submission_to_delivery": "من التسليم للمراجعة حتى التسليم للعميل"}
DIMENSIONS = {"runway": "المهلة", "workload": "عبء العمل", "start_weekday": "يوم بدء العمل", "period_of_month": "فترة الشهر"}
VALUES = {"short": "قصيرة", "adequate": "كافية", "higher": "أعلى", "lower": "أقل", "days_01_10": "الأيام 1-10", "days_11_20": "الأيام 11-20",
          "days_21_end": "من اليوم 21 حتى نهاية الشهر", "Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء", "Thursday": "الخميس",
          "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"}
STATES = {"positive": "إيجابية", "neutral": "محايدة", "negative": "سلبية", "not_classifiable": "غير قابلة للتصنيف"}
HEADLINES = {"speed_component_positive": "السرعة إيجابية", "deadline_component_positive": "مواعيد التسليم إيجابية",
             "overall_strong": "الحالة العامة قوية", "overall_good": "الحالة العامة جيدة", "late_rate_below_peers": "نسبة التأخير أقل من بقية المونتيرين"}
DIRECTION_WORDS = {"longer": "أطول", "shorter": "أقصر"}


def _reasons(params: Params) -> str:
    return "، ".join(f"{num(key)} {num(value)}" for key, value in params.get("reasons", {}).items())


def _value(p: Params) -> str:
    return f"{DIMENSIONS.get(p['dimension'], p['dimension'])} = {VALUES.get(str(p['value']), str(p['value']))}"


def _concentrated_group(p: Params) -> str:
    return types(p) if p["dimension"] == "video_type" else num(p["group"])


DATA = {
    "unattributed_projects": lambda p: (f"{num(p['projects'])} من {count(p['completed'], 'completed project')} بلا مونتير موثّق، وهي مستبعدة من كل نتائج "
                                        f"المونتيرين ({_reasons(p)})."),
    "deadline_not_classifiable": lambda p: (f"لا يمكن تصنيف موعد التسليم لـ {num(p['projects'])} من {count(p['attributed'], 'attributed project')} ({_reasons(p)})؛ "
                                            "ولا يتم تخمين أي وقت."),
    "eta_observed_after_work_started": lambda p: (f"في {num(p['projects'])} من {count(p['attributed'], 'attributed project')} سُجّل موعد Requested ETA المستخدم "
                                                  "لأول مرة بعد بدء العمل."),
    "unknown_status_spans": lambda p: (f"تحتوي {num(p['visits'])} زيارة حالة على {num(p['items'])} عنصرًا على حالة متقاعدة أو ممسوحة ولا تُنسب إلى أي مرحلة؛ "
                                       f"ويُستبعد {num(p['cycles_excluded_from_metrics'])} دورة من المقاييس لهذا السبب."),
    "label_fact_disagreement": lambda p: (f"{count(p['late_label_on_not_late'], 'project')} يحمل {mon('Late Delivery')} رغم أن أول Ready For Approval كان في "
                                          f"موعد Requested ETA أو قبله، و{num(p['on_time_label_on_late'])} يحمل {mon('On Time Delivery')} رغم أنه متأخر حسابيًا، و"
                                          f"{count(p['late_without_late_label'], 'late project')} حسابيًا لا يحمل مؤشر {mon('Late Delivery')}."),
    "video_type_not_benchmark_eligible": lambda p: (f"{count(p['projects'], 'project')} من نوع Video Type غير مؤهل لمعيار المقارنة "
                                                    f"({'، '.join(f'{mon(k)}: {num(v)}' for k, v in p['video_types'].items())})، لذلك لا تتوفر لها مقارنة سرعة."),
}


def _check_text(code: str, p: Params) -> str:
    texts: dict[str, Callable[[Params], str]] = {
        "speed_competitive": lambda r: (f"سرعة التنفيذ منافسة: وفق قاعدة السرعة المعتمدة على كامل السجل تكون القراءة "
                                        f"{STATES.get(str(r.get('state')), str(r.get('state')))} (أسرع {num(r['weights']['faster'])}، مماثلة "
                                        f"{num(r['weights']['similar'])}، أبطأ {count(r['weights']['slower'], 'project')})"),
        "late_cluster_in_short_runway": lambda r: (f"{num(r['short_runway_late'])} من {count(r['late'], 'late project')} بدأت بمهلة أقل مما يحتاجه التنفيذ "
                                                   f"المعتاد، مقابل {num(r['short_runway_not_late'])} من {count(r['not_late'], 'project')} غير متأخر"),
        "late_despite_typical_execution": lambda r: (f"{num(r['projects'])} من {count(r['late'], 'late project')} نُفّذت خلال المدة المعتادة لبقية المونتيرين "
                                                     "في الـ Video Type نفسه"),
        "peers_as_late_on_same_mix": lambda r: (f"على المزيج نفسه من أنواع Video Type كان بقية المونتيرين سيتأخرون بنسبة {pct_(r.get('expected_rate'))} مقابل "
                                                f"{pct_(r.get('observed_rate'))} فعليًا، لذا فالفرق المتبقي بعد مراعاة المزيج أقل من الفرق الجوهري"),
        "eta_passed_before_start": lambda r: f"{count(r['projects'], 'late project')} كانت قد تجاوزت موعد Requested ETA عند بدء العمل",
        "negative_labels_rising": lambda r: (f"ارتفعت نسبة المشاريع التي تحمل مؤشرًا سلبيًا محتسبًا من {pct_(r['comparison'])} "
                                             f"({count(r['comparison_sample'], 'project')}) إلى {pct_(r['current'])} ({count(r['current_sample'], 'project')})"),
        "negative_labels_behind_good_speed": lambda r: (f"{num(r['occurrences'])} مؤشرًا سلبيًا محتسبًا على {count(r['projects'], 'project')} في الفترة الحالية "
                                                        "رغم أن مكوّن السرعة إيجابي"),
        "workload_above_own_history": lambda r: (f"وسيط عبء العمل المتزامن عند البدء {num(r['current_median'])} في الفترة الحالية مقابل "
                                                 f"{num(r['history_median'])} في سجل المونتير نفسه"),
        "late_rate_rising_behind_good_speed": lambda r: f"ارتفعت نسبة التأخير من {pct_(r['comparison'])} إلى {pct_(r['current'])} بينما السرعة إيجابية",
    }
    row = _checks(p, code)
    return texts[code](row) if row else ""


T: dict[str, Callable[[Params], str]] = {
    # concentration
    "outcome_concentrated": lambda p: (f"يمثّل {_concentrated_group(p)} نسبة {pct_(p['outcome_share'])} من {OUTCOME_NAMES[p['outcome']]} "
                                       f"({num(p['group_outcomes'])} من {num(p['population_outcomes'])}) لكنه {pct_(p['population_share'])} فقط من المشاريع "
                                       f"({num(p['group_projects'])} من {num(p['population_projects'])})؛ ونسبته {pct_(p['group_rate'])} مقابل "
                                       f"{pct_(p['population_rate'])} إجمالًا" + (" (هذا الشهر ما زال جاريًا)" if p.get("partial_period") else "") + "."),
    "editor_outcome_concentrated": lambda p: (f"{num(p['group_outcomes'])} من {num(p['population_outcomes'])} من {OUTCOME_NAMES[p['outcome']]} لدى {who(p)} "
                                              f"تقع في {_concentrated_group(p)}، الذي يمثّل {pct_(p['population_share'])} من مشاريع المونتير "
                                              f"({num(p['group_projects'])} من {num(p['population_projects'])})."),
    "concentration_suggests_group_level_factor": lambda p: "يشير هذا إلى أن طبيعة العمل في هذه المجموعة نفسها، وليس فقط من يقوم به، تستحق الفهم.",
    "editor_outcomes_sit_in_group": lambda p: (f"يوضح هذا أين تقع {OUTCOME_NAMES[p['outcome']]} لدى المونتير؛ والمقارنة هنا مع مزيج مشاريعه هو فقط."),
    "group_may_differ_in_difficulty_or_scheduling": lambda p: "قد تختلف هذه المجموعة في النطاق أو موجز العمل أو الجدولة بطرق لا يسجلها Monday؛ وقد يستحق ذلك المراجعة.",
    "favourable_outcomes_sit_in_group": lambda p: "النتائج الإيجابية ممثلة بأكثر من حجمها في هذه المجموعة؛ وقد يوضح ذلك ما ينجح فيها.",
    "significance_concentration": lambda p: "معرفة أين تتركز النتائج تخبر الإدارة أين تنظر أولًا بدل الاعتماد على متوسطات الفريق.",
    "investigate_concentrated_group": lambda p: f"راجع المشاريع الـ {num(p['group_projects'])} وراء هذا الرقم قبل الوصول إلى استنتاج.",
    # workflow / bottlenecks
    "phase_time_medians": lambda p: "وسيط الوقت المنقضي حسب المرحلة: " + "؛ ".join(
        f"{PHASES.get(name, name)} {hrs(value['median_hours'])} ({count(value['n'], 'project')})" for name, value in p["phases"].items()) + ".",
    "largest_median_phase": lambda p: (f"أطول مرحلة حسب الوسيط هي {PHASES.get(p['largest_median_phase'], p['largest_median_phase'])}؛ وتُستبعد الفترات ذات "
                                       "الحالات المتقاعدة أو المفتوحة."),
    "significance_time_map": lambda p: "معرفة أين يذهب الوقت تفصل تنفيذ المونتير عن الانتظار قبله وبعده.",
    "investigate_largest_phase": lambda p: f"ابدأ بمرحلة {PHASES.get(p['largest_median_phase'], p['largest_median_phase'])} عند مناقشة وقت التسليم.",
    "late_projects_with_short_runway": lambda p: (f"{num(p['short_runway_late'])} من {count(p['late'], 'late project')} ({pct_(p['share_of_late_with_short_runway'])}) "
                                                  "دخلت In Progress بوقت قبل Requested ETA أقل من مدة التنفيذ المعتادة لبقية المونتيرين في الـ Video Type نفسه."),
    "short_runway_associated_with_lateness": lambda p: (f"ترتبط المهلة القصيرة بالتأخير في هذه العينة: تأخر {pct_(p['short_runway_late_rate'])} من "
                                                        f"{count(p['short_runway'], 'project')} بمهلة قصيرة مقابل {pct_(p['adequate_runway_late_rate'])} من "
                                                        f"{count(p['adequate_runway'], 'project')} بمهلة كافية."),
    "eta_passed_before_work_started": lambda p: f"{count(p['late_with_eta_passed_at_start'], 'late project')} كانت قد تجاوزت Requested ETA عند بدء In Progress.",
    "lateness_may_begin_before_editor_execution": lambda p: "يشير هذا إلى أن جزءًا من التأخير قد يبدأ قبل أن يبدأ المونتير عمله، وليس فقط أثناءه.",
    "upstream_scheduling_or_eta_setting": lambda p: "قد تستحق طريقة جدولة المشاريع أو تحديد مواعيد Requested ETA المراجعة (D46).",
    "significance_pre_editor": lambda p: "الحكم على المونتيرين بنسبة التأخير وحدها يتجاهل وقتًا لم يكن متاحًا لهم أصلًا.",
    "inspect_upstream_scheduling": lambda p: f"افحص الجدولة السابقة للمشاريع المتأخرة الـ {num(p['short_runway_late'])} ذات المهلة القصيرة.",
    "on_time_submissions_delivered_after_eta": lambda p: (f"{num(p['delivered_after_eta'])} من {count(p['submitted_on_or_before_eta_and_delivered'], 'project')} "
                                                          "سُلّمت للمراجعة في موعد Requested ETA أو قبله ثم سُلّمت للعميل بعده (وسيط انتظار المراجعة "
                                                          f"{hrs(p['median_review_wait_hours'])}، ووسيط المدة من التسليم للمراجعة حتى التسليم للعميل "
                                                          f"{hrs(p['median_submission_to_delivery_hours'])})."),
    "late_label_on_on_time_submission": lambda p: (f"{num(p['late_delivery_label_on_on_time_submission'])} منها تحمل مؤشر {mon('Late Delivery')} رغم أن المونتير "
                                                   "سلّم في الموعد."),
    "delay_after_editor_interval_not_editor_execution": lambda p: "يحدث هذا التأخير بعد انتهاء فترة المونتير، لذا فهو ليس من وقت تنفيذه.",
    "review_or_delivery_stage_may_add_delay": lambda p: "قد تستحق مرحلة المراجعة أو التسليم المراجعة؛ ولا يوضح Monday من يمسك المشروع حينها.",
    "significance_post_editor": lambda p: "قد يبدأ التأخير في التسليم للعميل بعد تسليم المونتير في الموعد؛ ويجب أن تعكس مؤشرات التأخير ذلك.",
    "inspect_review_and_delivery": lambda p: f"راجع خطوات الاعتماد والتسليم للمشاريع الـ {num(p['delivered_after_eta'])}.",
    # changes
    "late_rate_changed": lambda p: _change_rate(p),
    "negative_label_rate_changed": lambda p: _change_rate(p),
    "median_execution_changed": lambda p: (f"وسيط مدة التنفيذ {('لدى ' + who(p)) if p.get('editor_id') else 'للفريق'} في {types(p)} هو "
                                           f"{hrs(p['current_hours'])} في آخر {num(30)} يومًا مكتملة ({count(p['current_sample'], 'project')}) مقابل "
                                           f"{hrs(p['baseline_hours'])} في {'سجله السابق' if p.get('editor_id') else 'السجل السابق'} "
                                           f"({count(p['baseline_sample'], 'project')})، أي {'أبطأ' if p['pct_change'] > 0 else 'أسرع'} بنسبة "
                                           f"{abs_pct(p['pct_change'])}."),
    "change_improving": lambda p: f"هذا تحسّن لا يقل عن الفرق الجوهري ({_material(p)}).",
    "change_deteriorating": lambda p: f"هذا تراجع لا يقل عن الفرق الجوهري ({_material(p)}).",
    "change_differs_from_team": lambda p: "يختلف هذا التغيّر عن تغيّر بقية الفريق في الفترتين نفسيهما بما لا يقل عن الفرق الجوهري، لذا فالأرجح أنه خاص بهذا المونتير.",
    "team_comparison_unavailable": lambda p: (f"لا يمكن قياس تغيّر بقية المونتيرين في الفترتين نفسيهما عند الحد الأدنى المعتمد للعينة "
                                              f"({num(p.get('team_current_sample'))} و{count(p.get('team_baseline_sample') or 0, 'project')})، لذلك لا يستطيع Atlas "
                                              "تحديد ما إذا كان هذا التغيّر خاصًا بهذا المونتير."),
    "change_is_group_wide": lambda p: (f"{num(p['editors_same_direction'])} من {num(p['editors_with_both_periods'])} مونتيرين لديهم "
                                        f"{num(p['minimum_projects_per_editor'])} مشاريع على الأقل في الفترتين تحركوا في الاتجاه نفسه. يظهر هذا النمط لدى عدة "
                                        "مونتيرين وهو أقرب إلى نمط مشترك في سير العمل منه إلى نمط خاص بمونتير واحد."),
    "change_breadth_not_established": lambda p: (f"فقط {num(p['editors_same_direction'])} من {num(p['editors_with_both_periods'])} مونتيرين لديهم "
                                                  f"{num(p['minimum_projects_per_editor'])} مشاريع على الأقل في الفترتين تحركوا في الاتجاه نفسه، لذلك لا يصف "
                                                  "Atlas هذا التغيّر بأنه مشترك بين المونتيرين."),
    "workload_higher_in_same_period": lambda p: (f"كان عبء العمل المتزامن أعلى أيضًا في الفترة نفسها (الوسيط {num(p['workload_median_current'])} مقابل "
                                                 f"{num(p['workload_median_baseline'])})؛ والاثنان مرتبطان هنا، وهذا ليس دليلًا على السببية."),
    "team_moved_the_same_way": lambda p: ("تغيّر بقية الفريق بمقدار مماثل في الفترتين نفسيهما"
                                          + (f" ({signed_pct(p['team_pct_change'])})" if p.get("team_pct_change") is not None else "")
                                          + "، لذا فهذا التغيّر يعكس الفريق ومن غير المرجح أن يكون خاصًا بهذا المونتير."),
    "change_needs_context_before_conclusion": lambda p: "قد يعكس التغيّر مقارنة بخط الأساس مزيج المشاريع أو عبء العمل أو الجدولة؛ وقد يستحق ذلك المراجعة قبل أي استنتاج.",
    "significance_change": lambda p: "التغيّر الجوهري عن النمط المعتاد نقطة مبكرة للحوار، وليس حكمًا.",
    "investigate_change": lambda p: (f"قارن المشاريع الحديثة الـ {num(p['current_sample'])} بمشاريع خط الأساس الـ {num(p['baseline_sample'])} من حيث Video "
                                     "Type والمهلة وعبء العمل."),
    # workload
    "workload_bands": lambda p: (f"توضع المشاريع في شريحة عبء عمل أعلى أو أقل بمقارنة مشاريع المونتير المفتوحة الأخرى عند البدء بالوسيط الخاص به "
                                 f"({num(p.get('higher_band_projects', p.get('higher_band')))} أعلى، {num(p.get('lower_band_projects', p.get('lower_band')))} أقل)."),
    "higher_workload_associated_with_execution_time": lambda p: (f"يرتبط ارتفاع عبء العمل المتزامن بتنفيذ {DIRECTION_WORDS[p['direction']]} في هذه العينة: "
                                                                 f"الفرق الوسيط عبر {num(p['strata'])} مجموعة مونتير × Video Type هو "
                                                                 f"{abs_pct(p['median_stratum_pct'])}، و{num(p['strata_longer_when_higher'])} من "
                                                                 f"{num(p['strata'])} مجموعة تشير إلى الاتجاه نفسه."),
    "higher_workload_associated_with_late_rate": lambda p: (f"يرتبط ارتفاع عبء العمل المتزامن بنسبة تأخير {'أعلى' if p['difference'] > 0 else 'أقل'} في "
                                                            f"هذه العينة: {pct_(p['higher_rate'])} من {num(p['higher_band'])} مقابل "
                                                            f"{pct_(p['lower_rate'])} من {num(p['lower_band'])}."),
    "higher_workload_associated_with_negative_label_rate": lambda p: (f"يرتبط ارتفاع عبء العمل المتزامن بنسبة {'أعلى' if p['difference'] > 0 else 'أقل'} من "
                                                                      f"المشاريع ذات المؤشرات السلبية: {pct_(p['higher_rate'])} مقابل {pct_(p['lower_rate'])}."),
    "association_not_cause_workload": lambda p: "يتحرك عبء العمل والنتيجة معًا هنا، وهذا ليس دليلًا على السببية (الوقت المنقضي يشمل العمل المتوازي).",
    "workload_may_contribute": lambda p: "قد تستحق المهام المتزامنة المراجعة كأحد العوامل المحتملة.",
    "significance_workload": lambda p: "إذا ساءت النتائج عندما يتراكم العمل، فحجم التكليفات أداة تتحكم فيها الإدارة.",
    "compare_assignment_volume": lambda p: "قارن حجم التكليفات الأخيرة بعبء العمل التاريخي للمونتير.",
    # patterns
    "late_delivery_elevated_across_editors": lambda p: (f"التأخير في التسليم أعلى داخل {types(p)} منه خارجه لدى {num(p['elevated_editors'])} من "
                                                        f"{num(p['qualifying_editors'])} مونتيرين لديهم مشاريع كافية في الحالتين."),
    "short_runway_elevated_across_editors": lambda p: (f"تبدأ مشاريع {types(p)} بمهلة قصيرة أكثر من مشاريع المونتير نفسه الأخرى لدى "
                                                       f"{num(p['elevated_editors'])} من {num(p['qualifying_editors'])} مونتيرين مؤهلين."),
    "pattern_appears_process_wide": lambda p: "يظهر هذا النمط لدى عدة مونتيرين وهو أقرب إلى نمط مشترك في سير العمل منه إلى نمط خاص بمونتير واحد.",
    "shared_workflow_or_type_factor": lambda p: "قد يستحق سير عمل مشترك أو عامل خاص بهذا الـ Video Type المراجعة.",
    "late_delivery_elevated_for_one_editor_only": lambda p: (f"من بين {num(p['qualifying_editors'])} مونتيرين مؤهلين، فقط {mon(p.get('confined_editor_name'))} "
                                                             f"يتأخر داخل {types(p)} أكثر من خارجه."),
    "short_runway_elevated_for_one_editor_only": lambda p: (f"من بين {num(p['qualifying_editors'])} مونتيرين مؤهلين، فقط {mon(p.get('confined_editor_name'))} "
                                                            f"يتلقى مشاريع {types(p)} بمهلة قصيرة أكثر من عمله الآخر."),
    "pattern_confined_to_one_editor": lambda p: "يقتصر النمط على مونتير واحد في هذا الـ Video Type ولا يُعد مشتركًا.",
    "runway_pattern_is_upstream_context": lambda p: "تُحدَّد المهلة قبل أن يبدأ المونتير، لذا فهذا سياق عن العمل الذي تلقاه وليس عن تنفيذه.",
    "assignment_or_scheduling_for_this_editor": lambda p: "قد تستحق طريقة جدولة هذا الـ Video Type أو إسناده لهذا المونتير المراجعة.",
    "editor_specific_factor_possible": lambda p: "قد يوجد عامل خاص بالمونتير ويستحق حوارًا؛ والبيانات لا تحدده.",
    "working_practice_worth_understanding": lambda p: "قد تستحق طريقة تخطيط هذا المونتير أو ترتيبه للعمل المماثل الفهم والمشاركة؛ والبيانات لا تحددها.",
    "significance_shared": lambda p: "النمط المشترك يشير إلى العملية أو الجدولة وليس إلى شخص واحد.",
    "significance_confined_late_delivery": lambda p: "النمط المقتصر على مونتير واحد يستحق حوارًا محددًا قائمًا على الأدلة.",
    "significance_confined_short_runway": lambda p: "تركّز المهلة القصيرة في عمل مونتير واحد يغيّر طريقة قراءة نسبة تأخيره.",
    "review_shared_workflow": lambda p: "راجع سير العمل المشترك لهذا الـ Video Type لدى المونتيرين المتأثرين.",
    "review_confined_late_delivery": lambda p: "راجع مشاريع هذا المونتير في هذا الـ Video Type مع الأدلة قبل الاستنتاج.",
    "review_confined_short_runway": lambda p: "راجع طريقة جدولة هذا الـ Video Type لهذا المونتير.",
    "repeated_delay_combination": lambda p: (f"تأخرت مشاريع {types(p)} ذات {_value(p)} بنسبة {pct_(p['late_rate'])} ({num(p['late'])} من "
                                             f"{num(p['projects'])}) مقابل {pct_(p['overall_late_rate'])} لكل مشاريع هذا الـ Video Type "
                                             f"({num(p['video_type_projects'])})؛ وقد تم اختبار {num(p['cells_tested'])} تركيبة."),
    "combination_repeats_over_time": lambda p: "كانت التركيبة مرتفعة في النصفين الأول والثاني من السجل، لذا فهي ليست حالة عابرة.",
    "combination_may_mark_process_risk": lambda p: "قد تشير هذه التركيبة إلى خطر في العملية يستحق المراجعة.",
    "significance_repeated_delay": lambda p: "التركيبة المتكررة أكثر قابلية للتنفيذ من المتوسط: فهي تسمّي الموقف الذي يجب تجنبه.",
    "review_combination": lambda p: f"راجع طريقة تخطيط مشاريع هذا الـ Video Type ذات {_value(p)}.",
    "same_label_repeats_across_editors": lambda p: (f"يظهر {mon(p['label'])} {num(p['occurrences'])} مرة على مشاريع {types(p)} لدى {num(p['editors'])} "
                                                    f"مونتيرين ({count(p['type_projects'], 'project')} من هذا الـ Video Type إجمالًا)."),
    "label_pattern_not_one_editor": lambda p: "يتكرر المؤشر نفسه لدى عدة مونتيرين، لذا فمن غير المرجح أن يخص شخصًا واحدًا فقط.",
    "type_brief_or_process_may_drive_label": lambda p: "قد يستحق موجز العمل أو العملية الخاصة بهذا الـ Video Type المراجعة.",
    "significance_repeated_quality": lambda p: "المؤشر الذي يتكرر لدى عدة مونتيرين يشير إلى سبب مشترك يستحق البحث.",
    "review_label_in_type": lambda p: f"راجع التكرارات الـ {num(p['occurrences'])} لهذا المؤشر على مشاريع هذا الـ Video Type معًا.",
    "time_bucket_elevated": lambda p: (f"تأخرت المشاريع ذات {_value(p)} بنسبة {pct_(p['late_rate'])} مقابل {pct_(p['overall_late_rate'])} تتوقعها أنواع "
                                       f"Video Type الخاصة بها، وكانت مرتفعة في {num(p['months_elevated'])} من {num(p['months_tested'])} أشهر."),
    "timing_pattern_repeats": lambda p: "يتكرر أثر التوقيت عبر الأشهر ولا يظهر مرة واحدة فقط.",
    "timing_may_reflect_scheduling": lambda p: "قد تستحق الجدولة حول هذه الفترة المراجعة.",
    "significance_time_pattern": lambda p: "يمكن التخطيط حول نمط توقيت متكرر.",
    "review_timing": lambda p: "راجع طريقة جدولة العمل في هذه الفترة.",
    # person vs system
    "mix_adjusted_late_rate": lambda p: (f"على المزيج نفسه من أنواع Video Type، تتوقع نسب بقية المونتيرين {count(p['expected_late'], 'late project')} من "
                                         f"{num(p['covered_projects'])} ({pct_(p['expected_rate'])})؛ بينما كان لدى {who(p)} {num(p['observed_late'])} "
                                         f"({pct_(p['observed_rate'])})."),
    "editor_differs_from_peers_on_same_mix": lambda p: f"تختلف نسبة تأخير المونتير عما يتوقعه المزيج نفسه بمقدار {pp(p['excess'])}.",
    "same_conditions_late_rate": lambda p: (f"وبالمقارنة تحت مهلة مماثلة أيضًا، يكون الفرق {pp((p['same_conditions'] or {}).get('excess'))} "
                                            f"({count((p['same_conditions'] or {}).get('covered_projects') or 0, 'project')})."),
    "difference_persists_after_mix": lambda p: "يستمر الفرق بعد مراعاة أنواع Video Type التي عمل عليها المونتير.",
    "better_than_peers_after_mix": lambda p: "يتأخر المونتير أقل مما يتوقعه المزيج نفسه.",
    "raw_late_rate_gap": lambda p: f"نسبة التأخير الخام لدى {who(p)} هي {pct_(p['raw_editor_rate'])} مقابل {pct_(p['raw_peer_rate'])} لبقية المونتيرين.",
    "raw_gap_largely_reflects_work_mix": lambda p: (f"معظم هذا الفرق ({pct_(p['share_of_gap_explained_by_mix'])}) يعكس مزيج أنواع Video Type التي عمل عليها "
                                                    "المونتير، وليس اختلافًا في العمل المماثل."),
    "adjusted_gap_just_below_material": lambda p: (f"بعد مراعاة مزيج أنواع Video Type يصبح الفرق {pp(p['excess'])}، أي أقل بقليل من الفرق الجوهري؛ ويفسّر "
                                                   f"المزيج {pct_(p['share_of_gap_explained_by_mix'])} منه فقط."),
    "check_assignment_mix": lambda p: "قد يستحق مزيج التكليفات المراجعة قبل مقارنة المونتيرين بنسبة التأخير.",
    "gap_remains_worth_review": lambda p: "الفرق المتبقي قريب من الجوهري وقد يستحق المراجعة مع أدلة المشاريع.",
    "significance_editor_specific": lambda p: "الفرق الذي يبقى بعد تعديل المزيج أرجح أن يخص الفرد، ويستحق حوارًا محددًا قائمًا على الأدلة.",
    "significance_mix_explains": lambda p: "المقارنة الخام لنسبة التأخير مضللة هنا؛ فمزيج العمل يفسّر معظمها.",
    "significance_adjusted_gap_below_material": lambda p: "المقارنة الخام تبالغ في الفرق قليلًا فقط؛ والرقم المعدّل هو الأعدل للنقاش.",
    "review_editor_specific_deadline": lambda p: "راجع المشاريع المتأخرة للمونتير في أنواع Video Type المذكورة مع مهلتها وعبء العمل.",
    "review_assignment_mix": lambda p: "راجع كيفية توزيع أنواع Video Type على هذا المونتير مقارنة بالفريق.",
    # contradictions
    "conflict_fast_but_late": lambda p: f"مكوّن السرعة لدى {who(p)} إيجابي بينما مكوّن مواعيد التسليم سلبي في الفترة نفسها.",
    "conflict_slow_but_on_time": lambda p: f"مكوّن السرعة لدى {who(p)} سلبي بينما مكوّن مواعيد التسليم إيجابي في الفترة نفسها.",
    "conflict_better_than_team_but_mostly_late": lambda p: (f"مكوّن مواعيد التسليم لدى {who(p)} إيجابي (أفضل من بقية المونتيرين) بينما "
                                                            f"{num(p['late'])} من {num(p['deadline_classifiable_projects'])} من مشاريعه متأخرة "
                                                            f"({pct_(p['absolute_late_rate'])})."),
    "components_disagree_do_not_collapse": lambda p: "الأدلة متباينة: تشير المكوّنات إلى اتجاهات مختلفة وتُعرض جنبًا إلى جنب بدل دمجها في قراءة واحدة.",
    "conflict_points_outside_execution": lambda p: "عندما تختلف السرعة ومواعيد التسليم، قد يكمن التفسير خارج التنفيذ (المهلة، الجدولة) وقد يستحق المراجعة.",
    "significance_metric_conflict": lambda p: "الحالة الواحدة ستخفي هذا التعارض؛ ويجب أن يرى المدير الجانبين.",
    "investigate_conflict": lambda p: "تحقّق مما إذا كانت المشاريع المتأخرة تتركز في أنواع Video Type معينة أو فترات عبء عمل أو مهلة قصيرة.",
    "headline_late_rate_above_peers": lambda p: (f"نسبة التأخير لدى {who(p)} على السجل الكامل هي {pct_(p['late_rate'])} ({num(p['late'])} من "
                                                 f"{num(p['deadline_classifiable_projects'])}) مقابل {pct_(p['peer_late_rate'])} لبقية المونتيرين."),
    "check_speed_competitive": lambda p: "ومع ذلك، " + _check_text("speed_competitive", p) + ".",
    "check_late_cluster_in_short_runway": lambda p: "كذلك، " + _check_text("late_cluster_in_short_runway", p) + ".",
    "check_late_despite_typical_execution": lambda p: "كذلك، " + _check_text("late_despite_typical_execution", p) + ".",
    "check_peers_as_late_on_same_mix": lambda p: "كذلك، " + _check_text("peers_as_late_on_same_mix", p) + ".",
    "check_eta_passed_before_start": lambda p: "كذلك، " + _check_text("eta_passed_before_start", p) + ".",
    "headline_may_overstate_execution_cause": lambda p: ("الأدلة متباينة: رقم نسبة التأخير الرئيسي مرتفع، لكن أدلة سرعة التنفيذ لا تدعم تفسيرًا بسيطًا "
                                                         "بالسرعة. وهذا لا يعني أن المونتير لا دور له في حالات التأخير."),
    "lateness_may_arise_outside_execution": lambda p: "قد ينشأ جزء من التأخير قبل التنفيذ أو حوله (المهلة، Video Type، عبء العمل) وقد يستحق المراجعة.",
    "significance_bad_headline": lambda p: "لا تتوقف عند رقم نسبة التأخير عند مناقشة هذا المونتير.",
    "investigate_before_concluding_speed": lambda p: ("تحقّق مما إذا كانت حالات تأخير المونتير تتركز في أنواع Video Type معينة أو فترات عبء عمل أو مهلة "
                                                      "قصيرة قبل Requested ETA قبل استنتاج أن سرعة التنفيذ هي المشكلة الأساسية."),
    "favourable_headline": lambda p: f"العنوان الرئيسي لدى {who(p)} يبدو إيجابيًا ({'، '.join(HEADLINES.get(item, item) for item in p['favourable_headline'])}).",
    "check_negative_labels_rising": lambda p: "ومع ذلك، " + _check_text("negative_labels_rising", p) + ".",
    "check_negative_labels_behind_good_speed": lambda p: "ومع ذلك، " + _check_text("negative_labels_behind_good_speed", p) + ".",
    "check_workload_above_own_history": lambda p: "كذلك، " + _check_text("workload_above_own_history", p) + ".",
    "check_late_rate_rising_behind_good_speed": lambda p: "ومع ذلك، " + _check_text("late_rate_rising_behind_good_speed", p) + ".",
    "good_headline_hides_signal": lambda p: "الأدلة متباينة: قد يخفي العنوان الإيجابي إشارة مبكرة في قياس آخر.",
    "early_signal_worth_review": lambda p: "قد يستحق هذا نظرة مبكرة قبل أن يظهر في العنوان الرئيسي.",
    "significance_hidden_risk": lambda p: "نادرًا ما يُعاد فحص العناوين الجيدة؛ وهذا العنوان فيه إشارة تستحق المراجعة.",
    "review_hidden_signal": lambda p: "راجع مشاريع الفترة الحالية المذكورة في الأدلة.",
    # risks
    "risk_past_eta": lambda p: _risk(p),
    "risk_short_remaining_runway": lambda p: _risk(p),
    "risk_elapsed_beyond_typical": lambda p: _risk(p),
    "risk_editor_workload_above_own_high_percentile": lambda p: _risk(p),
    "risk_review_wait_beyond_typical": lambda p: _risk(p),
    "risk_signal_deserves_attention": lambda p: "هذه إشارة خطر تستحق الانتباه الآن، بينما العمل ما زال مفتوحًا.",
    "risk_signal_not_prediction": lambda p: "لدى هذه المشاريع حاليًا إشارات خطر تشبه ظروفًا كانت صعبة تاريخيًا؛ وهذا ليس توقعًا لنتيجتها.",
    "significance_open_risk": lambda p: "العمل المفتوح ما زال يمكن مساعدته؛ أما السجل فلا.",
    "check_open_past_eta": lambda p: "راجع المشاريع المذكورة الآن واتفق على موعد تسليم واقعي.",
    "check_open_short_remaining_runway": lambda p: "تحقّق مما إذا كان بإمكان المشاريع المذكورة الالتزام بموعد Requested ETA فعليًا.",
    "check_open_elapsed_beyond_typical": lambda p: "تحقّق مما يعطّل المشاريع المذكورة.",
    "check_open_editor_workload_above_own_high_percentile": lambda p: "تحقّق مما إذا كان يمكن تأجيل التكليفات الجديدة لهؤلاء المونتيرين.",
    "check_open_review_wait_beyond_typical": lambda p: "راجع طابور الاعتماد للمشاريع المذكورة.",
    "open_project_runway": lambda p: (f"بدأ مشروع {types(p)} المفتوح {num(p['monday_item_id'])} ({mon(p['editor_name']) if p.get('editor_name') else 'المونتير غير محدد'}) "
                                      f"بمهلة {hrs(p['runway_hours'])} مقابل مدة تنفيذ معتادة {hrs(p['typical_hours'])}."),
    "resembles_historical_projects": lambda p: (f"يشبه {count(p['similar_projects'], 'historical project')} من هذا الـ Video Type بمهلة "
                                                f"{VALUES.get(p['runway_band'], p['runway_band'])}، تأخر منها {num(p['similar_late'])} "
                                                f"({pct_(p['similar_late_rate'])})، مقابل {pct_(p['video_type_late_rate'])} لهذا الـ Video Type إجمالًا."),
    "base_rate_not_prediction": lambda p: "هذا معدل أساسي تاريخي، وليس توقعًا لهذا المشروع.",
    "significance_similarity": lambda p: "الموقف الذي يمر به هذا المشروع انتهى تاريخيًا بالتأخير أكثر من المعتاد.",
    "check_open_project": lambda p: f"راجع المشروع {num(p['monday_item_id'])} ما دام مفتوحًا.",
    # editor
    "speed_faster_than_comparable_team": lambda p: _speed(p, "أسرع"),
    "speed_slower_than_comparable_team": lambda p: _speed(p, "أبطأ"),
    "speed_pattern_within_video_type": lambda p: "تبقى كل مقارنة داخل Video Type واحد بالضبط وتستبعد المونتير من معيار المقارنة (D36).",
    "check_context_before_speed_conclusion": lambda p: "قد يستحق عبء العمل والمهلة ومزيج المشاريع المراجعة قبل اعتبار هذا مشكلة سرعة.",
    "significance_speed_faster": lambda p: "السرعة الثابتة داخل Video Type عبر عينة كافية نقطة قوة قائمة على الأدلة.",
    "significance_speed_slower": lambda p: "القراءة الأبطأ داخل Video Type نقطة محددة للفهم، وليست حكمًا عامًا.",
    "review_speed_context": lambda p: "راجع أنواع Video Type الأبطأ مع سياق عبء العمل والمهلة أدناه.",
    "recognise_evidence": lambda p: "شارك الأدلة مع المونتير؛ فهي محددة وقابلة للتحقق.",
    "negative_signals_concentrated_in_deadline": lambda p: (f"{num(p['top_count'])} من {num(p['occurrences'])} إشارة سلبية لدى {who(p)} هي "
                                                            f"{mon(p['top_label'])}، لذا فالأدلة السلبية تتركز في الالتزام بمواعيد التسليم وليس في مشكلات "
                                                            "جودة واسعة."),
    "negative_label_distribution": lambda p: (f"أكثر مؤشر سلبي تكرارًا على مشاريع {who(p)} هو {mon(p['top_label'])} ({num(p['top_count'])} من "
                                              f"{num(p['occurrences'])})."),
    "positive_label_distribution": lambda p: (f"أكثر مؤشر إيجابي تكرارًا على مشاريع {who(p)} هو {mon(p['top_label'])} ({num(p['top_count'])} من "
                                              f"{num(p['occurrences'])})."),
    "negative_label_pattern_meaning": lambda p: "تُضاف المؤشرات يدويًا، لذا فهذه الأعداد حد أدنى وتوضح أين لاحظت الإدارة مشكلات.",
    "positive_label_pattern_meaning": lambda p: "المؤشرات الإيجابية تقدير يُضاف يدويًا؛ وتوضح أين لاحظت الإدارة عملًا جيدًا.",
    "check_label_pattern_by_type_and_workload": lambda p: "قد يستحق التحقق مما إذا كانت هذه المؤشرات تتركز في أنواع Video Type معينة أو فترات عبء عمل أو مهلة قصيرة.",
    "significance_negative_labels": lambda p: "معرفة المشكلة الغالبة تركّز الحوار على مجال واحد بدل انطباع عام.",
    "significance_positive_labels": lambda p: "التقدير المحدد أكثر فائدة من الانطباع العام.",
    "review_label_pattern": lambda p: f"راجع المشاريع الـ {num(p['projects'])} ذات المؤشرات المذكورة في الأدلة.",
    # data
    "data_state_not_performance": lambda p: "هذه حالة بيانات وليست نتيجة أداء؛ تُستبعد المشاريع المتأثرة أو تُعلَّم، ولا يتم تخمينها أبدًا.",
}
for _code, _render in DATA.items():
    T[f"data_{_code}"] = _render
    T[f"significance_data_{_code}"] = lambda p: "النتائج تستبعد هذه المشاريع؛ وحجمها يوضح مقدار العمل الذي يستطيع التحليل رؤيته."
    T[f"fix_data_{_code}"] = lambda p: "صحّح بيانات المصدر في Monday حيثما أمكن؛ وسيضم Atlas المشاريع عند توفر الأدلة."


def _change_rate(p: Params) -> str:
    subject = f"{MEASURE_NAMES[p['measure']]} لدى {who(p)}" if p.get("editor_id") else f"{MEASURE_NAMES[p['measure']]} للفريق"
    against = (AGAINST if p.get("editor_id") else AGAINST_TEAM)[p["against"]]
    text = (f"{subject} هي {pct_(p['current'])} في آخر {num(30)} يومًا مكتملة ({count(p['current_sample'], 'project')}) مقابل {pct_(p['baseline'])} في "
            f"{against} ({count(p['baseline_sample'], 'project')})، أي تغيّر بمقدار {pp(p['difference'])}.")
    if p.get("editor_id") and p.get("team_current") is not None:
        text += f" وفي الفترتين نفسيهما انتقل بقية المونتيرين من {pct_(p['team_baseline'])} إلى {pct_(p['team_current'])}."
    return text


def _risk(p: Params) -> str:
    items = "، ".join(f"{num(row['monday_item_id'])} ({mon(row['status'])}{'، ' + mon(row['editor_name']) if row.get('editor_name') else ''})"
                      for row in p["items"][:10])
    more = f" و{num(len(p['items']) - 10)} غيرها" if len(p["items"]) > 10 else ""
    return f"{count(p['projects'], 'open project')} {SIGNALS[p['signal']]} في {num(p['retrieved_at'])}: {items}{more}."


def _speed(p: Params, verdict: str) -> str:
    rows = "؛ ".join(f"{' + '.join(mon(label) for label in row['labels'])}: {hrs(row['editor_median_hours'])} على {count(row['editor_projects'], 'project')} "
                     f"مقابل {hrs(row['comparator_median_hours'])} لـ {count(row['comparator_projects'], 'project')} من {num(row['comparator_editors'])} "
                     f"مونتيرين آخرين ({signed_pct(row['pct'])})" for row in p["video_types"])
    return f"{who(p)} {verdict} من الفريق المماثل في الفترة الحالية وفق قاعدة السرعة المعتمدة: {rows}."


def _p(finding: Any) -> Params:
    return finding.statements[0].params


def _measure_title(p: Params) -> str:
    return {"late_rate": "نسبة التأخير", "negative_label_rate": "نسبة المؤشرات السلبية"}.get(p.get("measure", ""), f"مدة التنفيذ في {types(p)}")


def _pattern_measure(p: Params) -> str:
    return "المهلة القصيرة" if p["measure"] == "short_runway" else "التأخير في التسليم"


def _better(f: Any) -> str:
    return "تحسّن" if f.direction == "favourable" else "تراجع"


TITLES: dict[str, Callable[[Any], str]] = {
    "concentration.negative": lambda f: (f"{OUTCOME_NAMES[_p(f)['outcome']]} تتركز في {_concentrated_group(_p(f))}" if not f.scope.editor_id
                                         else f"{who(_p(f))}: {OUTCOME_NAMES[_p(f)['outcome']]} تتركز في {_concentrated_group(_p(f))}"),
    "concentration.positive": lambda f: (f"{OUTCOME_NAMES[_p(f)['outcome']]} تتركز في {_concentrated_group(_p(f))}" if not f.scope.editor_id
                                         else f"{who(_p(f))}: {OUTCOME_NAMES[_p(f)['outcome']]} تتركز في {_concentrated_group(_p(f))}"),
    "workflow.time_map": lambda f: "أين يذهب وقت المشاريع",
    "bottleneck.pre_editor_runway": lambda f: "المشاريع المتأخرة تبدأ غالبًا بمهلة قصيرة جدًا",
    "bottleneck.post_editor": lambda f: "تأخير بعد التسليم في الموعد",
    "change.editor": lambda f: f"{who(_p(f))}: {_better(f)} في {_measure_title(_p(f))} مقارنة بسجله السابق",
    "change.team": lambda f: f"الفريق: {_better(f)} في {MEASURE_NAMES[_p(f)['measure']]}",
    "change.video_type": lambda f: (f"{types(_p(f))}: {_better(f)} في مدة التنفيذ" + (" لدى عدة مونتيرين" if _p(f).get("shared_across_editors") else "")),
    "workload.association": lambda f: "عبء العمل يتحرك مع النتائج على مستوى الفريق",
    "workload.overload_pattern": lambda f: f"{who(_p(f))}: ارتفاع عبء العمل يتزامن مع نتائج {'أسوأ' if f.direction == 'adverse' else 'أفضل'}",
    "pattern.shared_across_editors": lambda f: (f"{types(_p(f))}: {_pattern_measure(_p(f))} أكثر شيوعًا لدى عدة مونتيرين" if f.category == "system_pattern"
                                                else f"{types(_p(f))}: نمط {_pattern_measure(_p(f))} يقتصر على {mon(_p(f).get('confined_editor_name'))}"),
    "pattern.repeated_delay": lambda f: f"{types(_p(f))}: تأخير متكرر عندما {_value(_p(f))}",
    "pattern.repeated_quality": lambda f: f"{types(_p(f))}: {mon(_p(f)['label'])} يتكرر لدى عدة مونتيرين",
    "pattern.time": lambda f: f"نمط توقيت متكرر: {_value(_p(f))}",
    "person.mix_adjusted_deadline": lambda f: {"editor_specific_pattern": f"{who(_p(f))}: نسبة التأخير تختلف عن الزملاء في العمل المماثل",
                                               "hidden_context": f"{who(_p(f))}: مزيج العمل ورقم نسبة التأخير"}[f.category],
    "contradiction.metric_conflict": lambda f: f"{who(_p(f))}: السرعة ومواعيد التسليم تشيران إلى اتجاهين مختلفين",
    "contradiction.bad_headline": lambda f: f"{who(_p(f))}: رقم نسبة التأخير يحتاج إلى سياق",
    "contradiction.hidden_risk": lambda f: f"{who(_p(f))}: عنوان جيد يخفي إشارة",
    "risk.open_work": lambda f: f"العمل المفتوح: {count(_p(f)['projects'], 'project')} {SIGNALS[_p(f)['signal']]}",
    "risk.historical_similarity": lambda f: f"المشروع المفتوح {num(_p(f)['monday_item_id'])} يشبه أعمالًا تأخرت تاريخيًا",
    "editor.speed_pattern": lambda f: f"{who(_p(f))}: {'أسرع' if f.direction == 'favourable' else 'أبطأ'} من الفريق المماثل",
    "editor.label_pattern": lambda f: f"{who(_p(f))}: أين تتركز المؤشرات {'السلبية' if f.direction == 'adverse' else 'الإيجابية'}",
}

DATA_TITLES = {"data.unattributed_projects": "مشاريع بلا مونتير موثّق", "data.deadline_not_classifiable": "مشاريع بلا Requested ETA قابل للاستخدام",
               "data.eta_observed_after_work_started": "Requested ETA حُدّد بعد بدء العمل", "data.unknown_status_spans": "فترات حالة بحالات متقاعدة",
               "data.label_fact_disagreement": "مؤشرات تخالف موعد التسليم المحسوب", "data.video_type_not_benchmark_eligible": "أنواع Video Type بلا معيار مقارنة"}


def _fixed_title(title: str) -> Callable[[Any], str]:
    return lambda finding: title


for _type, _title in DATA_TITLES.items():
    TITLES[_type] = _fixed_title(_title)

QUESTIONS: dict[str, Callable[[Any, Params], str]] = {
    "bottleneck.pre_editor_runway": lambda f, p: "لماذا تدخل هذه المشاريع In Progress بمهلة أقل مما يحتاجه نوع Video Type الخاص بها عادة؟",
    "bottleneck.post_editor": lambda f, p: "ماذا يحدث بين التسليم في الموعد والتسليم للعميل في هذه المشاريع؟",
    "change.editor": lambda f, p: "ما الذي تغيّر لهذا المونتير بين الفترتين: مزيج المشاريع أم عبء العمل أم الجدولة؟",
    "change.team": lambda f, p: "ما الذي تغيّر في ظروف عمل الفريق بين الفترتين؟",
    "change.video_type": lambda f, p: "ما الذي تغيّر مؤخرًا في عمل هذا الـ Video Type؟",
    "workload.association": lambda f, p: "هل تتراكم التكليفات في أوقات تتزامن مع نتائج أسوأ؟",
    "workload.overload_pattern": lambda f, p: "ماذا يحدث لمشاريع هذا المونتير التي تبدأ بينما لديه عمل مفتوح أكثر؟",
    "pattern.shared_across_editors": lambda f, p: ("ما الذي في هذا الـ Video Type يجعل هذا النمط يظهر لدى عدة مونتيرين؟" if f.category == "system_pattern"
                                                   else "لماذا يظهر هذا النمط فقط في عمل مونتير واحد في هذا الـ Video Type؟"),
    "pattern.repeated_delay": lambda f, p: "لماذا تنتهي مشاريع هذه التركيبة متأخرة بشكل متكرر؟",
    "pattern.repeated_quality": lambda f, p: "لماذا يتكرر هذا المؤشر على مشاريع هذا الـ Video Type لدى عدة مونتيرين؟",
    "pattern.time": lambda f, p: "لماذا يرتفع التأخير في هذه الفترة؟",
    "person.mix_adjusted_deadline": lambda f, p: "في العمل المماثل، ما الذي يختلف لدى هذا المونتير؟",
    "contradiction.metric_conflict": lambda f, p: "لماذا تختلف قراءتا السرعة ومواعيد التسليم لدى هذا المونتير؟",
    "contradiction.bad_headline": lambda f, p: "هل نسبة تأخير هذا المونتير تتعلق بالتنفيذ، أم بالمهلة والعمل الذي تلقاه؟",
    "contradiction.hidden_risk": lambda f, p: "هل الإشارة خلف العنوان الجيد لهذا المونتير بداية تغيّر؟",
    "risk.open_work": lambda f, p: "أي من هذه المشاريع المفتوحة يحتاج إلى قرار اليوم؟",
    "risk.historical_similarity": lambda f, p: "هل ما زال يمكن تسليم هذا المشروع في الموعد؟",
    "editor.speed_pattern": lambda f, p: "ما الذي يفسّر قراءة سرعة هذا المونتير في هذه الأنواع من Video Type؟",
    "editor.label_pattern": lambda f, p: "ما الذي وراء المؤشرات على مشاريع هذا المونتير؟",
    "concentration.negative": lambda f, p: "ما المختلف في العمل ضمن هذه المجموعة؟",
    "concentration.positive": lambda f, p: "ما الذي ينجح في هذه المجموعة ويمكن تكراره؟",
    "workflow.time_map": lambda f, p: "أي مرحلة سيقلل تقصيرها وقت التسليم أكثر من غيرها؟",
}
DEFAULT_QUESTION = "ما الذي قد يفسّر هذا النمط؟"
DATA_QUESTION = "ما المطلوب لتسجيل هذه الأدلة في Monday؟"

LIMITATIONS = {
    "elapsed_clock_time_not_effort": "المدد وقت منقضٍ وليست جهدًا: تشمل الليالي وعطلات نهاية الأسبوع والعمل المتوازي (D3).",
    "video_type_is_the_only_complexity_control": "الـ Video Type هو الضابط الوحيد المتاح للتعقيد؛ فالطول والمواد وموجز العمل غير مسجلة.",
    "labels_are_hand_applied_lower_bound": "تُضاف المؤشرات يدويًا، لذا فأعدادها حد أدنى.",
    "association_not_causation": "هذا ارتباط في بيانات رصدية، وليس دليلًا على السببية.",
    "concurrency_counts_attributed_completed_first_cycles_only": "يحسب عبء العمل الدورات الأولى المكتملة والمنسوبة فقط، لذا فهو حد أدنى.",
    "unattributed_projects_excluded": "تُستبعد المشاريع التي لا يوجد لها مونتير موثّق.",
    "some_etas_first_observed_after_work_started": "سُجّل بعض مواعيد Requested ETA لأول مرة بعد بدء العمل.",
    "revision_cause_not_recorded": "لا يسجل Monday سبب حدوث التعديل.",
    "history_limited_to_ingest_window": "يبدأ السجل من فترة الاستيراد (2026-02-01 في بيئة الإنتاج).",
    "stage_owner_not_identifiable_shared_account": "لا يمكن تحديد من كان يمسك المشروع في هذه المرحلة (حساب مشترك للشركة).",
    "typical_execution_uses_whole_ingested_history": "مدة التنفيذ المعتادة تستخدم كامل سجل بقية المونتيرين في الـ Video Type نفسه.",
    "not_adjusted_for_video_type_mix": "غير معدّل حسب مزيج أنواع Video Type.",
    "current_snapshot_only": "مبني على لقطة Monday الحالية فقط.",
    "several_combinations_tested": "تم اختبار عدة تركيبات؛ وقد تظهر بعض الخلايا المرتفعة بالصدفة، لذلك يُشترط تكرارها عبر الزمن.",
    "no_evidence_of_actual_cause": "توضح البيانات ما حدث، وليس لماذا حدث.",
    "includes_a_partial_period": "يشمل شهرًا ما زال جاريًا.",
    "sample_near_minimum": "العينة قريبة من حدها الأدنى.",
    "uses_proposed_parameters_not_approved": "يستخدم عتبات مقترحة لم تعتمدها الإدارة (للمراجعة فقط).",
}

UNCERTAINTY = {
    ("strong", "association"): "أدلة قوية على ارتباط؛ لكنها ما زالت ليست دليلًا على السببية.",
    ("moderate", "association"): "أدلة متوسطة على ارتباط في هذه العينة.",
    ("weak", "association"): "مؤشر مبكر على ارتباط؛ والأدلة محدودة.",
    ("strong", "other"): "أدلة قوية: يصمد النمط عبر عدة شرائح مستقلة.",
    ("moderate", "other"): "أدلة متوسطة.",
    ("weak", "other"): "أدلة محدودة: تعامل مع هذا كمؤشر مبكر.",
    ("strong", "fact"): "حقيقة مباشرة من لقطة Monday الحالية.",
    ("moderate", "fact"): "حقيقة مباشرة من لقطة Monday الحالية.",
    ("weak", "fact"): "حقيقة مباشرة من لقطة Monday الحالية.",
}
LEVEL_NAMES = {"weak": "محدودة", "moderate": "متوسطة", "strong": "قوية"}
FACTOR_NAMES = {"sample_size": "حجم العينة", "replication": "التكرار في شرائح مستقلة", "contradicting_evidence": "الأدلة المعاكسة",
                "data_completeness": "اكتمال البيانات", "independent_examples": "الأمثلة المستقلة", "direct_observation": "ملاحظة مباشرة"}
ASSESSMENTS = {"supports": "يدعم", "limits": "يحدّ", "not_assessed": "لم يُقيَّم", "information": "للعلم"}
JOIN = "؛ "
