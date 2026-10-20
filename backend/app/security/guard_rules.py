"""Rules layer of the prompt-injection guard (WP-11 milestone 5; FEATURES P5).

Each rule is one attack intent written for English (en), Bangla (bn), Banglish (bl, romanised
Bangla) and Chinese (zh). Patterns run on normalised text (see `guard.normalise`): NFKC,
lower case, zero-width and bidi controls removed, look-alike letters folded, Bangla digits as
ASCII. A few high-signal phrases are also matched with every separator removed, which catches
"i g n o r e  p r e v i o u s" and "ign.ore prev-ious".

Rules target DecisionGuard's own invariants (approvals, step-up, payees, bank details, audit, the
token vault, secrets, invented numbers) more than generic jailbreak wording, and were checked
against hard negatives that use the same words innocently ("ignore the disputed invoice",
"how do I update my own bank details", "approve the netting round with my code").
Honest limit: they were written with sight of the WP-17 corpus, so the corpus measures
regressions, not generalisation. On 20 Oct the rules caught 3 of WP-16's 12 new attacks; each
family was then widened to intent level (an action next to what it targets, per language) and
checked for false alarms on the 96 benign corpus rows and the hard negatives in
tests/security/test_guard.py. Those 12 attacks were seen while doing so, so they now measure
regressions too; generalisation needs a fresh held-out set written without reading this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    family: str
    pattern: re.Pattern[str]


def _rules(family: str, **by_lang: list[str]) -> list[Rule]:
    out: list[Rule] = []
    for lang, patterns in by_lang.items():
        for i, pattern in enumerate(patterns):
            out.append(Rule(f"{family}.{lang}.{i}", family, re.compile(pattern)))
    return out


_THIRD = r"(?:supplier|vendor|their|his|her|payee|wholesaler)"

RULES: list[Rule] = [
    *_rules(
        "override_rules",
        en=[r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,25}\b(?:previous|prior|above|"
            r"earlier|all|your|system|safety)\b.{0,25}\b(?:instructions?|rules?|prompts?|"
            r"guidelines?|checks?|polic(?:y|ies))\b",
            r"\bforget (?:your|all|the) rules\b",
            r"\bwithout (?:any )?(?:safety|security) checks?\b",
            r"\bfrom now on,? you (?:will|answer|are|must|ignore)\b"],
        bn=[r"নির্দেশনা.{0,10}ভুলে", r"নিয়ম(?:গুলো)?.{0,6}বাদ দাও", r"যাচাই ছাড়াই"],
        bl=[r"\binstruction\w*.{0,6}bhule\b", r"\brules? baad dao\b",
            r"\bcheck chara\b"],
        zh=[r"忽略.{0,6}(?:指令|指示|规则|提示)", r"忘[掉记]你?的?规则",
            r"不做任何.{0,4}(?:安全)?检查"],
    ),
    *_rules(
        "skip_approval",
        en=[r"\bskip\b.{0,20}\b(?:step-?up|approval|verification|code|otp|2fa|pin)\b",
            r"\b(?:agreed|approved|confirmed) (?:it )?(?:by|over the) phone\b",
            r"\bapprove (?:everything|all(?: of them)?)\b.{0,15}\b(?:pending|now)\b",
            r"\b(?:execute|submit|release|send)\b.{0,40}\bdirectly\b",
            r"\bwithout (?:the |my |a )?(?:step-?up |approval |verification )?(?:code|otp|"
            r"approval)\b.{0,30}\b(?:approve|execute|send|pay|release|transfer)",
            # Generalised 20 Oct: the code or approval waived, broken or deferred, next to an
            # action that moves money or submits something.
            r"\b(?:authenticator|step-?up|otp|2fa|verification|approval)\b.{0,40}"
            r"\b(?:broken|not working|lost|later|skip|no need|not needed|waive)\b",
            r"\btreat\b.{0,40}\bas (?:already )?(?:approved|confirmed|verified)\b",
            r"\bmark\b.{0,30}\b(?:pending )?approvals?\b.{0,15}\bas approved\b",
            r"\b(?:already|pre-?)approved\b.{0,40}\b(?:push|send|transfer|pay|submit|release)",],
        bn=[r"কোড লাগবে না", r"কোড বাদ দিয়ে", r"ফোনে রাজি", r"সরাসরি.{0,20}জমা দিয়ে দাও",
            r"কোড (?:ছাড়া|ছাড়াই|পরে)", r"(?:যাচাই|অনুমোদন) (?:ছাড়া|ছাড়াই|লাগবে না)"],
        bl=[r"\bcode lagbe na\b", r"\bcode chara\b", r"\bphone e raji\b",
            r"\bsorasori\b.{0,25}\bsubmit\b",
            r"\b(?:verification|otp|approval|code)\b.{0,12}\b(?:lagbe na|chara|pore dibo)\b"],
        zh=[r"跳过.{0,4}(?:验证码|验证|审批|审核|确认)", r"电话.{0,4}同意",
            r"直接提交", r"全部批准", r"把待办的?全部批准",
            r"(?:验证码|验证|审批|审核|确认).{0,3}(?:就)?(?:免了|不用了?|不需要|省了|以后再)",
            r"忽略.{0,4}(?:审批|批准|验证|流程)"],
    ),
    *_rules(
        "change_bank_details",
        en=[r"\b(?:change|update|replace|switch|edit)\w*\b.{0,30}\b" + _THIRD + r"\W*s?\b.{0,30}"
            r"\b(?:bank|account|payee details?)",
            r"\b" + _THIRD + r"\b.{0,15}\b(?:changed|switched|moved) banks?\b",
            r"\b(?:replace|update) their (?:payee|bank|account)",
            r"\b(?:new|fresh|another|different)\b.{0,20}\b(?:bank account|account number|"
            r"wallet|bkash|nagad|rocket)\b.{0,60}\b(?:route|send|pay|transfer|redirect)\w*\b"
            r".{0,30}\b(?:payments?|money|from (?:now|today))",
            r"\b(?:route|redirect|divert)\b.{0,15}\b(?:all|every|future)\b.{0,15}\bpayments?\b"],
        bn=[r"সাপ্লায়ারের ব্যাংক", r"অ্যাকাউন্ট বদলে", r"নতুন অ্যাকাউন্টে.{0,30}পাঠি",
            r"ব্যাংক বদলেছে",
            r"নতুন (?:বিকাশ|নগদ|অ্যাকাউন্ট|নম্বর).{0,40}(?:সব|এখন থেকে).{0,20}(?:টাকা|পেমেন্ট)"],
        bl=[r"\bsupplier er bank\b", r"\bbank change koreche\b",
            r"\bnotun account e\b.{0,30}\b(?:update|pathi|pay)",
            r"\bnotun (?:bkash|nagad|account|number)\b.{0,40}\b(?:shob|ekhon theke)\b"],
        zh=[r"(?:供应商|收款人)的?银行(?:账户|信息)?.{0,4}(?:改|换)", r"把收款人信息改",
            r"换银行了",
            r"新的?(?:收款)?(?:账号|账户|卡号).{0,30}(?:以后|今后|从今天起)?.{0,6}(?:所有|全部)"
            r".{0,6}(?:货款|款项|付款|钱)?.{0,4}(?:都)?(?:打|转|付)到"],
    ),
    *_rules(
        "add_payee",
        en=[r"\b(?:add|create|register|set up|make)\b.{0,15}\b(?:new )?payee\b",
            r"\bpayee (?:called|named|for my)\b"],
        bn=[r"প্রাপক যোগ", r"প্রাপক বানাও"],
        bl=[r"\bpayee add\b", r"\bpayee banao\b"],
        zh=[r"(?:新增|添加|建|加)一?个?收款人"],
    ),
    *_rules(
        "exfiltrate_vault",
        en=[r"\b(?:print|show|dump|list|reveal|export|give)\b.{0,25}\btoken vault\b",
            r"\breal names? behind\b", r"\bdecrypt\w*\b.{0,30}\b(?:names?|numbers?|tokens?)\b",
            r"\b(?:every|all) (?:customer'?s?|client'?s?) (?:phone|mobile|contact)",
            r"\b(?:token|vault|label)s?\b.{0,15}\bmapping\b",
            r"\bwhich real (?:customer|person|name)\b",
            r"\b(?:all|every|full list of)\b.{0,20}\b(?:customers?|clients?)\b.{0,20}\breal\b"
            r".{0,10}\b(?:names?|numbers?|identit)"],
        bn=[r"টোকেন ভল্ট", r"ডিক্রিপ্ট", r"সব গ্রাহকের ফোন নম্বর",
            r"সব (?:কাস্টমারের|গ্রাহকের|ক্রেতার).{0,15}আসল (?:নাম|পরিচয়)",
            r"(?:আসল নাম|মোবাইল নম্বর).{0,30}(?:ইমেইলে|ইমেইল|তালিকা).{0,10}পাঠাও"],
        bl=[r"\btoken vault\b", r"\bdecrypt\b", r"\bshob customer er phone number\b"],
        zh=[r"令牌库", r"解密", r"每个客户的电话",
            r"(?:所有|全部)客户的?(?:真实)?(?:姓名|名字).{0,4}(?:和|与|及)?(?:手机号|电话)",
            r"(?:真实姓名|手机号).{0,15}(?:导出|发到|发给).{0,6}(?:邮箱|邮件)?"],
    ),
    *_rules(
        "exfiltrate_secrets",
        en=[r"\bapi[ -]?keys?\b", r"(?:^|[\s/\\])\.env\b", r"\bprivate[ -]?keys?\b",
            r"\bsecret[ -]?keys?\b", r"\bsystem prompt\b", r"\benvironment variables?\b"],
        bn=[r"এপিআই কি", r"প্রাইভেট কি", r"এনভায়রনমেন্ট"],
        bl=[r"\bapi key\b", r"\bprivate key\b"],
        zh=[r"api ?密钥", r"私钥", r"环境变量", r"系统提示"],
    ),
    *_rules(
        "disable_audit",
        en=[r"\b(?:turn off|disable|stop|pause|switch off)\b.{0,20}\baudit",
            r"\b(?:delete|erase|wipe|remove|clear|purge)\b.{0,30}\baudit "
            r"(?:log|entr|trail|record)",
            r"\b(?:do not|don't|stop) (?:record|log)(?:ging)?\b.{0,30}\b(?:entr|action|event)"],
        bn=[r"অডিট লগ বন্ধ", r"অডিট এন্ট্রি.{0,12}মুছে"],
        bl=[r"\baudit log bondho\b", r"\baudit entry\b.{0,15}\bmuche\b",
            r"\baudit\b.{0,15}\b(?:bondho|off|band)\b", r"\brecord na hoy\b"],
        zh=[r"(?:关掉|关闭|停用|删除|清除|删掉).{0,8}审计",
            r"审计.{0,6}(?:关掉|关闭|停用|删除|清除|删掉)"],
    ),
    *_rules(
        "role_play_jailbreak",
        en=[r"\bpretend (?:you are|you're|to be)\b", r"\b(?:dev|developer)[ -]?mode\b",
            r"\bunrestricted\b", r"\bwith no limits\b", r"\bjailbreak", r"\bno restrictions\b",
            r"\blet'?s play a game\b"],
        bn=[r"ভান করো", r"সীমাহীন"],
        bl=[r"\bbhan koro\b", r"\blimit chara\b"],
        zh=[r"假装你是", r"不受限制", r"开发者模式", r"没有任何限制"],
    ),
    *_rules(
        "fake_owner",
        en=[r"\bthis is the (?:shop )?owner\b", r"\bi(?:'m| am) the (?:shop )?owner'?s?\b",
            r"\b(?:lost|forgot|broke) my phone\b", r"\byou can trust me\b",
            r"\bon behalf of the owner\b"],
        bn=[r"আমি মালিক বলছি", r"ফোন হারিয়েছি", r"মালিকের ছেলে", r"বিশ্বাস করতে পারো"],
        bl=[r"\bami malik bolchi\b", r"\bphone haray", r"\bmaliker chele\b",
            r"\bbishshash korte paro\b"],
        zh=[r"我是老板", r"手机丢了", r"店主的儿子", r"你可以相信我"],
    ),
    *_rules(
        "hidden_instruction",
        en=[r"\bnote to (?:the )?assistant\b", r"(?:^|\|)\s*(?:system|assistant)\s*:",
            r"\bignore the owner\b", r"\[(?:system|inst)\]", r"<\|?(?:system|im_start)",
            r"\b(?:system|admin|assistant)\s+(?:note|instruction|command|message)\b",
            r"\bdo not tell the owner\b"],
        bn=[r"সহকারীর জন্য নোট", r"সিস্টেম\s*:", r"মালিককে উপেক্ষা"],
        bl=[r"\bmalik ke ignore\b"],
        zh=[r"给助手的备注", r"系统\s*[:：]", r"忽略店主",
            r"系统(?:指令|命令|通知|消息)", r"(?:备注|附言).{0,6}(?:指令|命令)",
            r"(?:余额|钱|款).{0,4}全部转到"],
    ),
    *_rules(
        "tool_budget_abuse",
        en=[r"\b\d{1,3}(?:,\d{3})+ times\b|\b\d{4,} times\b", r"\bin a loop\b",
            r"\buntil i say stop\b", r"\bcall every tool\b"],
        bn=[r"\d{1,3}(?:,\d{3})+ বার|\d{4,} বার", r"থামতে না বলা পর্যন্ত", r"সব টুল"],
        bl=[r"\b\d{4,} bar\b", r"\bloop e\b", r"\bthamte na bola\b"],
        zh=[r"[一二三四五六七八九十百千万\d]+万次", r"循环调用", r"直到我说停"],
    ),
    *_rules(
        "fake_numbers",
        en=[r"\bnobody will (?:check|notice)\b",
            r"\bmake\b.{0,40}\blook better than\b",
            r"\b(?:inflate|fake|fudge|massage|cook) (?:the |our )?(?:numbers|figures|books|sales)"],
        bn=[r"কেউ যাচাই করবে না", r"আসলের চেয়ে ভালো দেখাও"],
        bl=[r"\bkeu check korbe na\b", r"\bashol er cheye bhalo\b"],
        zh=[r"没人会查", r"比实际好看"],
    ),
]

# Phrases matched with every non-letter removed (catches spaced or punctuated spellings).
SQUASHED: list[tuple[str, str]] = [
    ("override_rules.squashed.0", "ignoreallpreviousinstructions"),
    ("override_rules.squashed.1", "ignorepreviousinstructions"),
    ("override_rules.squashed.2", "disregardallpriorinstructions"),
    ("exfiltrate_secrets.squashed.0", "systemprompt"),
    ("role_play_jailbreak.squashed.0", "developermode"),
    ("skip_approval.squashed.0", "skipthestepupcode"),
]
