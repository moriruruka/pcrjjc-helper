"""公主连结角色名 / 别称数据与匹配工具。

数据分两层：
1. 权威单位列表来自 pcrdfans.com/units 的 __NEXT_DATA__（351 个单位，含 cn/us 服）；
2. 本地 CHARA_NAME 提供中文官译 / 日文 / 英文 / 黑话别称。
两者按 6 位 id 的 uid4 = id // 100 合并。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_SCHEMA = 2
UNITS_URL = "https://pcrdfans.com/units"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 这些角色没有正常可用的竞技场头像 / 未实装，仅用于旧本地表兜底。
UNAVAILABLE_CHARA = {
    1072,
    1073,
    1102,
    1183,
    1184,
    1204,
    1205,
    1206,
    1217,
    1218,
    1243,
    1244,
}

# 由工具生成的内置角色数据（JSON，键是 4 位角色 id 的字符串）。
# 第一项是台服官译（展示名），后面依次是日文、英文、B 服译名、黑话别称等。
CHARA_NAME: dict[str, list[str]] = json.loads(
    r"""{"1001":["日和","ヒヨリ","Hiyori","日和莉","猫拳","东山","🐱👊"],"1002":["优衣","ユイ","Yui","种田","普田","由衣","结衣","ue","↗↘↗↘"],"1003":["怜","レイ","Rei","剑圣","普怜","伶"],"1004":["禊","ミソギ","Misogi","未奏希","炸弹","炸弹人","熊孩子","💣"],"1005":["茉莉","マツリ","Matsuri","跳跳虎","老虎","虎","跳刀虎","🐅"],"1006":["茜里","アカリ","Akari","妹法","阿卡丽","妹妹法"],"1007":["宫子","ミヤコ","Miyako","布丁","布","幽灵","🍮"],"1008":["雪","ユキ","Yuki","小雪","镜子","镜法","伪娘","男孩子","男孩纸","雪哥"],"1009":["杏奈","アンナ","Anna","中二","煤气罐"],"1010":["真步","マホ","Maho","狐狸","真扎","咕噜灵波","真布","🦊"],"1011":["璃乃","リノ","Rino","妹弓"],"1012":["初音","ハツネ","Hatsune","hego","星法","星星法","⭐法","睡法","拍大星"],"1013":["七七香","ナナカ","Nanaka","娜娜卡","77k","77香","十十力"],"1014":["霞","カスミ","Kasumi","香澄","侦探","杜宾犬","驴","驴子","驴妹","🔍"],"1015":["美里","ミサト","Misato","圣母"],"1016":["铃奈","スズナ","Suzuna","暴击弓","暴弓","爆击弓","爆弓","辣妹弓","政委"],"1017":["香织","カオリ","Kaori","琉球犬","狗子","狗","狗拳","🐶","🐕","🐶👊🏻","🐶👊"],"1018":["伊绪","イオ","Io","老师","魅魔","依绪"],"1020":["美美","ミミ","Mimi","兔子","兔兔","兔剑","萝卜霸断剑","人参霸断剑","天兔霸断剑","🐇","🐰"],"1021":["胡桃","クルミ","Kurumi","铃铛","🔔"],"1022":["依里","ヨリ","Yori","姐法","姐姐法"],"1023":["绫音","アヤネ","Ayane","熊锤","🐻🔨","🐻"],"1025":["铃莓","スズメ","Suzume","女仆","妹抖","悠木碧","umb","雀"],"1026":["铃","リン","Rin","松鼠","🐿","🐿️"],"1027":["惠理子","エリコ","Eriko","病娇"],"1028":["咲恋","サレン","Saren","充电宝","青梅竹马","幼驯染","院长","园长","🔋","普电"],"1029":["望","ノゾミ","Nozomi","偶像","小望","🎤"],"1030":["妮诺","ニノン","Ninon","妮侬","扇子"],"1031":["忍","シノブ","Shinobu","普忍","鬼父","💀"],"1032":["秋乃","アキノ","Akino","哈哈剑"],"1033":["真阳","マヒル","Mahiru","奶牛","🐄","🐮","真☀"],"1034":["优花梨","ユカリ","Yukari","由加莉","黄骑","酒鬼","奶骑","圣骑","🍺","🍺👻","油咖喱"],"1036":["镜华","キョウカ","Kyouka","小仓唯","xcw","小苍唯","8岁","八岁","喷水萝","八岁喷水萝","8岁喷水萝"],"1037":["智","トモ","Tomo","卜毛","脱毛","智爷"],"1038":["栞","シオリ","Shiori","tp弓","小栞","白虎弓","白虎妹","栞栞","白虎"],"1040":["碧","アオイ","Aoi","香菜","香菜弓","绿毛弓","毒弓","绿帽弓","绿帽"],"1042":["千歌","チカ","Chika","绿毛奶","精灵奶"],"1043":["真琴","マコト","Makoto","狼","🐺","月月","朋","狼姐"],"1044":["伊莉亚","イリヤ","Iriya","伊利亚","伊莉雅","伊利雅","yly","吸血鬼","那个女人"],"1045":["空花","クウカ","Kuuka","抖m","抖"],"1046":["珠希","タマキ","Tamaki","猫剑","🐱剑","🐱🗡️"],"1047":["纯","ジュン","Jun","黑骑","saber"],"1048":["美冬","ミフユ","Mifuyu","子龙","赵子龙"],"1049":["静流","シズル","Shizuru","姐姐"],"1050":["美咲","ミサキ","Misaki","大眼","眼球法","👀","👁️","👁"],"1051":["深月","ミツキ","Mitsuki","眼罩","抖s","医生"],"1052":["莉玛","リマ","Rima","Lima","草泥马","羊驼","🦙","🐐"],"1053":["莫妮卡","モニカ","Monika","毛二力","莫尼卡"],"1054":["纺希","ツムギ","Tsumugi","裁缝","蜘蛛侠","🕷️","🕸️"],"1055":["步未","アユミ","Ayumi","步美","路人","路人妹"],"1056":["流夏","ルカ","Ruka","大姐","大姐头","儿力","luka","刘夏","露卡","卢卡"],"1057":["吉塔","ジータ","Jiita","姬塔","团长","吉他","🎸","骑空士","qks"],"1058":["贪吃佩可","ペコリーヌ","Pecorine","Pekoriinu","佩可莉姆","吃货","佩可","公主","饭团","🍙"],"1059":["可可萝","コッコロ","Kokkoro","可可罗","妈","普白","普妈","kkr"],"1060":["凯留","キャル","Karyl","Kyaru","凯露","百地希留耶","希留耶","Kiruya","黑猫","臭鼬","普黑","接头霸王","街头霸王","猫猫","猫猫头"],"1061":["矛依未","ムイミ","Muimi","诺维姆","Noemu","夏娜","511","无意义","天楼霸断剑","姆咪","母咪"],"1063":["亚里莎","アリサ","Arisa","鸭梨瞎","瞎子","亚里沙","鸭梨傻","亚丽莎","亚莉莎","瞎子弓","🍐🦐","yls"],"1064":["雪菲","シェフィ","Shephy","Shefi","紫布菜","冰龙"],"1065":["嘉夜","カヤ","Kaya","憨憨龙","龙拳","🐲👊🏻","🐉👊🏻","接龙笨比","鬼道嘉夜","卡雅","卡亚","卡娅"],"1066":["祈梨","イノリ","Inori","梨老八","李老八","龙锤","🐲🔨"],"1067":["帆稀","ホマレ","Homare","穗希","龙妈","龙王","大仓唯"],"1068":["拉比林斯达","ラビリスタ","Labyrista","Rabirisuta","迷宫女王","模索路晶","模索路","晶","迷宫女","王晶","晶姐","日日日"],"1069":["真那","マナ","Mana","霸瞳皇帝","千里真那","千里","霸瞳","霸铜"],"1070":["似似花","ネネカ","Neneka","变貌大妃","现士实似似花","現士実似々花","現士実","现士实","nnk","448","捏捏卡","变貌","大妃","奶奶卡"],"1071":["克莉丝提娜","クリスティーナ","Kurisutiina","誓约女君","克莉丝提娜·摩根","Christina","Cristina","克总","女帝","克","摩根","克姐"],"1075":["贪吃佩可(夏日)","ペコリーヌ(サマー)","Pecorine(Summer)","Pekoriinu(Summer)","佩可莉姆(夏日)","水吃","水饭","水吃货","水佩可","水公主","水饭团","水🍙","泳吃","泳饭","泳吃货","泳佩可","泳公主","泳饭团","泳🍙","泳装吃货","泳装公主","泳装饭团","泳装🍙","佩可(夏日)","🥡","👙🍙","泼妇"],"1076":["可可萝(夏日)","コッコロ(サマー)","Kokkoro(Summer)","水白","水妈","水可","水可可","水可可萝","水可可罗","泳装妈","泳装可可萝","泳装可可罗"],"1077":["铃莓(夏日)","スズメ(サマー)","Suzume(Summer)","水女仆","水妹抖"],"1078":["凯留(夏日)","キャル(サマー)","Karyl(Summer)","Kyaru(Summer)","凯露(夏日)","水黑","水黑猫","水臭鼬","泳装黑猫","泳装臭鼬","潶","溴","💧黑","流泪猫猫头"],"1079":["珠希(夏日)","タマキ(サマー)","Tamaki(Summer)","水猫剑","水猫","渵","💧🐱","💧🐱🗡️","水🐱🗡️"],"1080":["美冬(夏日)","ミフユ(サマー)","Mifuyu(Summer)","水子龙","水美冬"],"1081":["忍(万圣节)","シノブ(ハロウィン)","Shinobu(Halloween)","万圣忍","瓜忍","鬼忍","🎃忍","🎃💀"],"1082":["宫子(万圣节)","ミヤコ(ハロウィン)","Miyako(Halloween)","万圣宫子","万圣布丁","狼丁","狼布丁","万圣🍮","🐺🍮","🎃🍮","👻🍮"],"1083":["美咲(万圣节)","ミサキ(ハロウィン)","Misaki(Halloween)","万圣美咲","万圣大眼","瓜眼","🎃眼","🎃👀","🎃👁️","🎃👁"],"1084":["千歌(圣诞节)","チカ(クリスマス)","Chika(Xmas)","圣诞千歌","圣千","蛋鸽","🎄💰🎶","🎄千🎶","🎄1000🎶"],"1085":["胡桃(圣诞节)","クルミ(クリスマス)","Kurumi(Xmas)","圣诞胡桃","圣诞铃铛"],"1086":["绫音(圣诞节)","アヤネ(クリスマス)","Ayane(Xmas)","圣诞熊锤","蛋锤","圣锤","🎄🐻🔨","🎄🐻"],"1087":["日和(新年)","ヒヨリ(ニューイヤー)","Hiyori(NewYear)","新年日和","春猫","👘🐱"],"1088":["优衣(新年)","ユイ(ニューイヤー)","Yui(NewYear)","新年优衣","春田","新年由衣"],"1089":["怜(新年)","レイ(ニューイヤー)","Rei(NewYear)","春剑","春怜","春伶","新春剑圣","新年怜","新年剑圣"],"1090":["惠理子(情人节)","エリコ(バレンタイン)","Eriko(Valentine)","情人节病娇","恋病","情病","恋病娇","情病娇","青椒"],"1091":["静流(情人节)","シズル(バレンタイン)","Shizuru(Valentine)","情人节静流","情姐","情人节姐姐","恋姐"],"1092":["安","アン","An","胖安","55kg","小安"],"1093":["露","ルゥ","Ruu","逃课女王","补考女帝"],"1094":["古蕾娅","グレア","Gurea","龙姬","古雷娅","古蕾亚","古雷亚","古蕾雅","🐲🐔","🐉🐔"],"1095":["空花(大江户)","クウカ(オーエド)","Kuuka(Ooedo)","江户空花","江户抖m","江m","花m","江花","大江m","花抖"],"1096":["妮诺(大江户)","ニノン(オーエド)","Ninon(Ooedo)","江户扇子","忍扇"],"1097":["雷姆","レム","Remu","蕾姆"],"1098":["拉姆","ラム","Ramu"],"1099":["爱蜜莉雅","エミリア","Emiria","艾米莉亚","emt"],"1100":["铃奈(夏日)","スズナ(サマー)","Suzuna(Summer)","瀑击弓","水爆","水爆弓","水暴","瀑","水暴弓","水暴击弓","水政委","瀑弓","泳装暴弓","泳装爆弓","泳装政委"],"1101":["伊绪(夏日)","イオ(サマー)","Io(Summer)","水魅魔","水老师","泳装魅魔","泳装老师","水io"],"1103":["咲恋(夏日)","サレン(サマー)","Saren(Summer)","水电","泳装充电宝","泳装咲恋","水着咲恋","水电站","水电宝","水充","👙🔋"],"1104":["真琴(夏日)","マコト(サマー)","Makoto(Summer)","水狼","浪","水🐺","泳狼","泳月","泳月月","泳朋","水月","水月月","水朋","👙🐺"],"1105":["香织(夏日)","カオリ(サマー)","Kaori(Summer)","水狗","泃","水🐶","水🐕","泳狗","水狗拳"],"1106":["真步(夏日)","マホ(サマー)","Maho(Summer)","水狐狸","水狐","水壶","水真步","水maho","氵🦊","水🦊","💧🦊"],"1107":["碧(插班生)","アオイ(編入生)","Aoi(Hennyuusei)","生菜","插班碧","学院碧","转校弓","转学弓"],"1108":["克萝依","クロエ","Kuroe","克罗依","华哥","黑江","黑江花子","花子"],"1109":["琪爱儿","チエル","Chieru","千爱瑠","切露","茄露","茄噜","切噜","佐仓"],"1110":["优妮","ユニ","Yuni","真行寺由仁","由仁","优尼","u2","优妮辈先","辈先","书记","uni","先辈","仙贝","油腻","优妮先辈","学姐","18岁黑丝学姐","咖啡人"],"1111":["镜华(万圣节)","キョウカ(ハロウィン)","Kyouka(Halloween)","万圣镜华","万圣小仓唯","万圣xcw","猫仓唯","黑猫仓唯","mcw","猫唯","猫仓","喵唯"],"1112":["禊(万圣节)","ミソギ(ハロウィン)","Misogi(Halloween)","万圣禊","万圣炸弹人","瓜炸弹人","万圣炸弹","万圣炸","瓜炸","南瓜炸","万圣节禊","万圣熊孩","🎃💣"],"1113":["美美(万圣节)","ミミ(ハロウィン)","Mimi(Halloween)","万圣兔","万圣兔子","万圣兔兔","绷带兔","绷带兔子","万圣美美","绷带美美","瓜兔","万圣🐰","绷带🐰","🎃🐰","万圣🐇","绷带🐇","🎃🐇"],"1114":["露娜","ルナ","Runa","Luna","露仓唯","露cw"],"1115":["克莉丝提娜(圣诞节)","クリスティーナ(クリスマス)","Kurisutiina(Xmas)","Christina(Xmas)","Cristina(Xmas)","圣诞克","圣诞克总","圣诞女帝","蛋克","蛋壳","圣克","必胜客"],"1116":["望(圣诞节)","ノゾミ(クリスマス)","Nozomi(Xmas)","圣诞望","圣诞偶像","蛋偶像","蛋望"],"1117":["伊莉亚(圣诞节)","イリヤ(クリスマス)","Iriya(Xmas)","圣诞伊莉亚","圣诞伊利亚","圣诞伊莉雅","圣诞伊利雅","圣诞yly","圣诞吸血鬼","圣伊","圣yly","伊利丹"],"1118":["贪吃佩可(新年)","ペコリーヌ(ニューイヤー)","Pecorine(NewYear)","佩可莉姆(新年)","春吃","新吃","新年吃货","年货"],"1119":["可可萝(新年)","コッコロ(ニューイヤー)","Kokkoro(NewYear)","春可可","春白","新年妈","春妈"],"1120":["凯留(新年)","キャル(ニューイヤー)","Karyl(NewYear)","Kyaru(NewYear)","凯露(新年)","春凯留","春黑猫","春黑","春臭鼬","新年凯留","新年黑猫","新年臭鼬","唯一神","神"],"1121":["铃莓(新年)","スズメ(ニューイヤー)","Suzume(NewYear)","春铃莓","春女仆","春妹抖","新年铃莓","新年女仆","新年妹抖"],"1122":["霞(魔法少女)","カスミ(マジカル)","Kasumi(MagiGirl)","魔法少女霞","魔法侦探","魔法杜宾犬","魔法驴","魔法驴子","魔驴","魔法霞","魔法少驴"],"1123":["栞(魔法少女)","シオリ(マジカル)","Shiori(MagiGirl)","魔法少女栞","魔法tp弓","魔法小栞","魔法白虎弓","魔法白虎妹","魔法白虎","魔栞","魔弓","魔法弓","法弓"],"1124":["卯月(NGs)","ウヅキ(デレマス)","Udsuki(DEREM@S)","卯月(偶像大师)","卯月","卵用","Udsuki(DEREMAS)","岛村卯月","Udsuki"],"1125":["凛(NGs)","リン(デレマス)","Rin(DEREM@S)","凛(偶像大师)","凛","Rin(DEREMAS)","涩谷凛","西部凛"],"1126":["未央(NGs)","ミオ(デレマス)","Mio(DEREM@S)","未央(偶像大师)","未央","Mio(DEREMAS)","本田未央","Mio"],"1127":["铃(游侠)","リン(レンジャー)","Rin(Ranger)","骑兵松鼠","游侠松鼠","游骑兵松鼠","护林员松鼠","护林松鼠","游侠🐿️","武松","钻头松鼠"],"1128":["真阳(游侠)","マヒル(レンジャー)","Mahiru(Ranger)","骑兵奶牛","游侠奶牛","游骑兵奶牛","护林员奶牛","护林奶牛","游侠🐄","游侠🐮","牛叉"],"1129":["璃乃(奇幻)","リノ(ワンダー)","Rino(Wonder)","璃乃(奇境)","璃乃(仙境)","爽弓","爱丽丝弓","爱弓","兔弓","奇境妹弓","奇幻妹弓","奇幻璃乃","仙境妹弓","白丝妹弓","爱丽丝妹弓"],"1130":["步未(奇幻)","アユミ(ワンダー)","Ayumi(Wonder)","步未(奇境)","步未(仙境)","路人兔","兔人妹","爱丽丝路人","奇境路人","奇幻路人","奇幻步未","仙境路人","爱丽丝路人妹","梦路"],"1131":["流夏(夏日)","ルカ(サマー)","Ruka(Summer)","泳装流夏","水流夏","泳装刘夏","水刘夏","泳装大姐","泳装大姐头","水大姐","水大姐头","水儿力","泳装儿力","水流"],"1132":["杏奈(夏日)","アンナ(サマー)","Anna(Summer)","泳装中二","泳装煤气罐","水中二","水煤气罐","冲","冲二"],"1133":["七七香(夏日)","ナナカ(サマー)","Nanaka(Summer)","泳装娜娜卡","泳装77k","泳装77香","水娜娜卡","水77k","水77香","水七七香","泳装七七香","水七"],"1134":["初音(夏日)","ハツネ(サマー)","Hatsune(Summer)","水星","海星","水hego","水星法","泳装星法","水⭐法","水睡法","湦","泳装初音","水初音","夏日初音"],"1135":["美里(夏日)","ミサト(サマー)","Misato(Summer)","水母","泳装圣母","水圣母"],"1136":["纯(夏日)","ジュン(サマー)","Jun(Summer)","泳装黑骑","水黑骑","泳装纯","水纯","小次郎"],"1137":["茜里(天使)","アカリ(エンジェル)","Akari(Angel)","天使妹法","天使茜里","丘比特妹法","天妹"],"1138":["依里(天使)","ヨリ(エンジェル)","Yori(Angel)","天使姐法","天使依里","丘比特姐法","天姐"],"1139":["纺希(万圣节)","ツムギ(ハロウィン)","Tsumugi(Halloween)","万圣裁缝","万圣蜘蛛侠","🎃🕷️","🎃🕸️","万裁","瓜裁","鬼裁","鬼才"],"1140":["怜(万圣节)","レイ(ハロウィン)","Rei(Halloween)","万圣剑圣","万剑","瓜剑","瓜怜","万圣怜","鬼剑","鬼怜"],"1141":["茉莉(万圣节)","マツリ(ハロウィン)","Matsuri(Halloween)","万圣跳跳虎","万圣老虎","瓜虎","万圣虎","🎃🐅"],"1142":["莫妮卡(魔法少女)","モニカ(マジカル)","Monika(MagiGirl)","魔法少女莫妮卡","魔二力","魔卡少女"],"1143":["智(魔法少女)","トモ(マジカル)","Tomo(MagiGirl)","魔法少女智","琪露诺","9智","⑨"],"1144":["秋乃(圣诞节)","アキノ(クリスマス)","Akino(Xmas)","圣剑","生煎","圣诞哈哈剑","哈哈剑(圣诞节)","圣哈","蛋哈","蛋剑"],"1145":["咲恋(圣诞节)","サレン(クリスマス)","Saren(Xmas)","圣诞充电宝","圣电","圣诞咲恋"],"1146":["优花梨(圣诞节)","ユカリ(クリスマス)","Yukari(Xmas)","蛋黄","由加莉(圣诞节)","圣诞黄骑","圣诞圣骑","蛋骑","黄骑(圣诞节)","圣黄"],"1147":["矛依未(新年)","ムイミ(ニューイヤー)","Muimi(NewYear)","新年511","春511","春11","春矛","512"],"1150":["似似花(新年)","ネネカ(ニューイヤー)","Neneka(NewYear)","新年似似花","春似似花","春nnk","春花","新年nnk","春妃","春448"],"1155":["可可萝(祭服)","コッコロ(儀装束)","Kokkoro(Costume)","可可萝(仪装束)","礼妈","仪妈","仪装妈","姨妈","礼白"],"1156":["优衣(祭服)","ユイ(儀装束)","Yui(Costume)","优衣(仪装束)","礼ue","礼装ue","礼装优衣","仪装ue","礼衣","礼田"],"1157":["霞(夏日)","カスミ(サマー)","Kasumi(Summer)","水驴","泳装驴","沪"],"1158":["莉玛(灰姑娘)","リマ(シンデレラ)","Rima(Cinderella)","人形羊驼","人驼","灰驼","灰姑娘羊驼","灰羊"],"1159":["真琴(灰姑娘)","マコト(シンデレラ)","Makoto(Cinderella)","灰姑娘狼","灰狼"],"1160":["真步(灰姑娘)","マホ(シンデレラ)","Maho(Cinderella)","灰姑娘狐狸","灰狐狸","灰狐","灰壶","茶狐","茶壶"],"1162":["克萝依(圣学祭)","クロエ(聖学祭)","Kuroe(Seigakusai)","运动华","运动华哥","圣学祭华","圣学祭克萝依","圣华"],"1163":["琪爱儿(圣学祭)","チエル(聖学祭)","Chieru(Seigakusai)","千爱瑠(圣学祭)","运动切噜","圣学祭切噜","圣学祭琪爱儿","圣学祭千爱瑠","圣爱瑠"],"1164":["优妮(圣学祭)","ユニ(聖学祭)","Yuni(Seigakusai)","圣优妮","圣uni","运动优妮","运动服","罗塞塔"],"1165":["祈梨(时间旅行)","イノリ(タイムトラベル)","Inori(TimeTravel)","时间旅行龙锤","穿越龙锤","穿越梨老八","军装龙锤","元首龙锤","元首","元老八"],"1166":["嘉夜(时间旅行)","カヤ(タイムトラベル)","Kaya(TimeTravel)","时间旅行龙拳","穿越龙拳","水手龙","水手龙拳","时空龙拳"],"1167":["碧(作业服)","アオイ(作業服)","Aoi(Sagyoufuku)","碧(工作服)","工菜","韭菜","工作碧","贡菜"],"1168":["珠希(作业服)","タマキ(作業服)","Tamaki(Sagyoufuku)","珠希(工作服)","工猫贼","工猫剑","工贼","工珠希"],"1169":["美冬(作业服)","ミフユ(作業服)","Mifuyu(Sagyoufuku)","美冬(工作服)","电子龙","工子龙","工龙","工头"],"1170":["惠理子(夏日)","エリコ(サマー)","Eriko(Summer)","泳装惠理子","泳装病娇","水病","水病娇","水饺","水娇"],"1171":["静流(夏日)","シズル(サマー)","Shizuru(Summer)","泳装静流","泳装姐姐","水姐","水姐姐","水解","沮"],"1172":["望(夏日)","ノゾミ(サマー)","Nozomi(Summer)","泳装偶像","泳装望","水望","水偶像","夏日偶像","夏日望","潒"],"1173":["千歌(夏日)","チカ(サマー)","Chika(Summer)","泳装千歌","水千","汘","泳千"],"1174":["纺希(夏日)","ツムギ(サマー)","Tsumugi(Summer)","泳装裁缝","泳装纺希","水裁缝","水裁","水彩","水纺希","漨"],"1175":["深月(大江户)","ミツキ(オーエド)","Mitsuki(Ooedo)","江月","江S","江户深月","大江户深月"],"1176":["雪(大江户)","ユキ(オーエド)","Yuki(Ooedo)","江雪","江哥","江户雪","江户小雪","江户雪哥","大江户雪"],"1177":["香织(万圣节)","カオリ(ハロウィン)","Kaori(Halloween)","万圣狗","瓜狗","万圣狗拳"],"1178":["妮诺(万圣节)","ニノン(ハロウィン)","Ninon(Halloween)","万圣扇","瓜扇","万圣扇子"],"1179":["铃奈(万圣节)","スズナ(ハロウィン)","Suzuna(Halloween)","万圣暴弓","瓜弓","瓜暴弓","万圣爆弓","瓜爆弓"],"1180":["克蕾琪塔","クレジッタ","Kurejitta","富婆","信用卡"],"1181":["兰法","ランファ","Ranfa","Ranpha","兰法妈妈","兰妈妈","兰妈"],"1182":["美空","ミソラ","Misora","坏女人","魅空","流魅空","流美空"],"1185":["花凛","カリン","Karin","佳凛","绿色恶魔","绿魔","绿毛恶魔"],"1190":["伊绪(黑暗)","イオ(ノワール)","Io(Noir)","黑老师","黑魅魔"],"1191":["空花(黑暗)","クウカ(ノワール)","Kuuka(Noir)","黑m","暗m"],"1192":["真阳(圣诞节)","マヒル(クリスマス)","Mahiru(Xmas)","圣牛","蛋牛","圣诞奶牛","圣诞牛"],"1193":["璃乃(圣诞节)","リノ(クリスマス)","Rino(Xmas)","圣诞妹弓","圣诞璃乃","弹弓","蛋弓","诞弓"],"1199":["宫子(圣诞节)","ミヤコ(クリスマス)","Miyako(Xmas)","圣诞布丁","圣诞宫子","诞丁","蛋丁","但丁"],"1200":["静流(黑暗)","シズル(ノワール)","黑姐姐","黑姐"],"1207":["雪菲(新年)","シェフィ(ニューイヤー)","Shephy(NewYear)","Shefi(NewYear)","新年雪菲","春雪菲","春菲","春冰龙"],"1208":["流夏(新年)","ルカ(ニューイヤー)","Ruka(NewYear)","春流夏","春流"],"1209":["伊莉亚(新年)","イリヤ(ニューイヤー)","Iriya(NewYear)","新年伊莉亚","新年伊利亚","新年伊莉雅","新年伊利雅","新年yly","新年吸血鬼","春伊","春yly","伊莉旦"],"1210":["贪吃佩可(超载)","ペコリーヌ(オーバーロード)","Pecorine(Overload)","Pekoriinu(Overload)","超载吃","超吃","超载佩可","超载佩","超佩"],"1211":["凯留(超载)","キャル(オーバーロード)","Karyl(Overload)","凯露(超载)","Kyaru(Overload)","超载凯留","超凯留","超载黑猫","超黑","超猫","超威蓝猫"],"1212":["拉比林斯达(超载)","ラビリスタ(オーバーロード)","Labyrista(Overload)","Rabirisuta(Overload)","超载晶","超晶"],"1213":["胡桃(舞台)","クルミ(ステージ)","Kurumi(Stage)","舞台胡桃","舞桃","演员","舞胡","芜湖","舞铃","舞台铃","戏铃"],"1214":["美咲(舞台)","ミサキ(ステージ)","Misaki(Satge)","舞台大眼","舞台眼","舞台美咲","泥头车大眼","车眼"],"1215":["步未(怪盗)","アユミ(怪盗)","Ayumi(Kaitou)","怪盗路人","怪盗路人妹"],"1216":["祈梨(怪盗)","イノリ(怪盗)","Inori(Kaitou)","怪盗祈梨","怪盗龙锤","忍龙","忍龙锤"],"1219":["杏奈(海盗)","アンナ(パイレーツ)","Anna(Pirates)","海盗中二","海盗杏奈","船长中二","船二"],"1220":["忍(海盗)","シノブ(パイレーツ)","Shinobu(Pirates)","海盗忍","海贼忍","海忍","水手忍","手忍"],"1221":["碧(露营)","アオイ(キャンプ)","Aoi(Camp)","露营碧","露碧","野菜"],"1222":["优花梨(露营)","ユカリ(キャンプ)","Yukari(Camp)","露营优花梨","露优花梨","露花梨","露营黄骑","露黄骑","露黄"],"1223":["斑比","ヴァンピィ","Vampy","Vania","斑比酱","钉宫"],"1224":["日和(夏日)","ヒヨリ(サマー)","Hiyori(Summer)","水猫拳","水日和"],"1225":["怜(夏日)","レイ(サマー)","Rei(Summer)","水怜","水剑圣"],"1226":["优衣(夏日)","ユイ(サマー)","Yui(Summer)","水优衣","水ue","水田","泳衣","游依","水草"],"1227":["镜华(夏日)","キョウカ(サマー)","Kyouka(Summer)","泳装镜华","水镜华","水xcw","水仓唯","水cw","scw"],"1228":["禊(夏日)","ミソギ(サマー)","Misogi(Summer)","未奏希(夏日)","水禊","水炸弹人","水炸","水未奏希","泳装炸弹人","泳装未奏希"],"1229":["美美(夏日)","ミミ(サマー)","Mimi(Summer)","水美美","泳装美美","水兔","水兔兔","水兔子"],"1230":["爱梅斯","アメス","Amesu","菲欧","爱美斯","艾美斯","艾梅斯"],"1231":["真步(探险家)","マホ(エクスプローラー)","Maho(Explorer)","野狐","探狐","尻狐","屁狐","屁胡"],"1232":["绫音(探险家)","アヤネ(エクスプローラー)","Ayane(Explorer)","野锤","野炊"],"1233":["涅娅","ネア","Nea","小黄","史莱姆","黄史莱姆"],"1235":["铃(万圣节)","リン(ハロウィン)","Rin(Halloween)","瓜松鼠","鬼松鼠","万圣松鼠"],"1236":["智(万圣节)","トモ(ハロウィン)","Tomo(Halloween)","瓜智","鬼智","万圣智"],"1237":["七七香(万圣节)","ナナカ(ハロウィン)","Nanaka(Halloween)","鬼七","瓜七","万圣七七香","鬼泣"],"1238":["克莉丝提娜(野性)","クリスティーナ(ワイルド)","Kurisutiina(Wild)","兔克","兔女郎克","野克"],"1239":["茉莉(野性)","マツリ(ワイルド)","Matsuri(Wild)","小虎","野老虎"],"1240":["茜里(圣诞节)","アカリ(クリスマス)","Akari(Xmas)","圣妹","圣诞妹法"],"1241":["依里(圣诞节)","ヨリ(クリスマス)","Yori(Xmas)","圣姐","圣诞姐法"],"1242":["纯(圣诞节)","ジュン(クリスマス)","Jun(Xmas)","圣骑","白骑","圣黑骑","圣诞黑骑"],"1245":["帆稀(新年)","ホマレ(ニューイヤー)","Homare(NewYear)","春龙妈","新年龙妈"],"1246":["美里(新年)","ミサト(ニューイヤー)","Misato(NewYear)","春母","新母","新年圣母"],"1247":["深月(新年)","ミツキ(ニューイヤー)","Mitsuki(NewYear)","春月","新月","新年深月"],"1251":["珠希(咖啡馆)","タマキ(カフェ)","Tamaki(Cafe)","猫咖","咖啡猫"],"1252":["莫妮卡(咖啡馆)","モニカ(カフェ)","Monika(Cafe)","莫妮咖","咖二力"],"1253":["可可萝(游侠)","コッコロ(レンジャー)","Kokkoro(Ranger)","游妈","狗妈","游侠可可萝","游侠妈","游白"],"1254":["栞(游侠)","シオリ(レンジャー)","Shiori(Ranger)","游栞","游侠栞","游侠tp弓"],"1701":["环奈","カンナ","Kanna","桥本环奈","红二力","毛大力","毛小力","毛六力","可大萝","大可萝","缝合怪","一环"],"1702":["环奈(振袖)","カンナ(振袖)","Kanna(Furisode)","振袖环奈","春环","春奈","春环奈","二环","振环奈","振环","甄嬛","震动环","年糕环奈","年糕环"],"1801":["日和(公主)","ヒヨリ(プリンセス)","Hiyori(Princess)","公主日和","公猫","炎拳猫","火猫","炎拳"],"1802":["优衣(公主)","ユイ(プリンセス)","Yui(Princess)","公主优衣","公主yui","公主种田","公主田","公主ue","掉毛优衣","掉毛yui","掉毛ue","掉毛","飞翼优衣","飞翼ue","飞翼","飞翼高达","飞田","羽田","羽衣","毛衣","pfue"],"1803":["怜(公主)","レイ(プリンセス)","Rei(Princess)","公主怜","公剑","风剑","pf怜"],"1804":["贪吃佩可(公主)","ペコリーヌ(プリンセス)","Pecorine(Princess)","佩可莉姆(公主)","Pekoriinu(Princess)","公主吃","公主饭","公主吃货","公主佩可","公主饭团","公主🍙","命运高达","高达","命运公主","高达公主","命吃","春哥高达","🤖🍙","🤖","公吃","pf吃"],"1805":["可可萝(公主)","コッコロ(プリンセス)","Kokkoro(Princess)","公主妈","月光妈","蝶妈","蝴蝶妈","月光蝶妈","公主可","公主可萝","公主可可萝","月光可","月光可萝","月光可可萝","蝶可","蝶可萝","蝶可可萝","公可","pf妈","飞妈"],"1806":["凯留(公主)","キャル(プリンセス)","Karyl(Princess)","Kyaru(Princess)","凯露(公主)","公主黑猫","公主猫","公主猫猫头","白猫"],"1807":["初音&栞","ハツネ&シオリ","Hatsune&Shiori","星弓","星栞","双子弓","姐妹弓","姊妹弓","姐妹丼","姊妹丼","姐妹井","贴贴弓","替身弓","白金之星","食堂泼辣酱","初音栞","星法栞"],"1808":["禊&美美&镜华","ミソギ&ミミ&キョウカ","Misogi&Mimi&Kyouka","小小甜心","狱三家","小御三家"],"1809":["秋乃&咲恋","アキノ&サレン","Akino&Saren","咲哈哈","哈哈电","哈哈咲","哈电","电哈","光焰"],"1810":["安&古蕾雅","アン＆グレア","An&Gurea","双姬","古安","龙安"],"1901":["菲欧","フィオ","Fio"],"1907":["大古","タイゴ","Taigo","大吾","鬼道大吾"],"1909":["涅比亚","ネビア","Nevia","Nebia"],"1910":["真崎","マサキ","Masaki"],"1911":["米涅尔β","ミネルβ","MineruBeta","米涅尔","ミネル","Mineru"],"1913":["和正","カズマサ","Kazumasa"],"1914":["豪绅","ゴウシン","Goushin"],"1916":["基洛","キイロ","Kiiro"],"1917":["赞恩","ゼーン","Seen","大舅哥","Zane"],"1919":["阿佐尔德","アンゾールド","Anzoorudo","猪哥","Azold"],"4031":["骷髅","髑髏","Dokuro","骷髅老爹","老爹"],"9000":["祐树","ユウキ","Yuuki","骑士","骑士君"]}"""
)

_SPLIT_RE = re.compile(r"[\s\u3000,，、+＋/|｜;；]+")
_SPACE_RE = re.compile(r"[\s\u3000]+")
_ID_RE = re.compile(r"^(?:id)?(\d{3,6})$", re.IGNORECASE)


def normalize(text: Any) -> str:
    """归一化角色名：全角转半角、去空白、转小写。"""

    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    value = _SPACE_RE.sub("", value)
    return value.casefold()


def _clean_names(names: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        if raw is None:
            continue
        name = str(raw).strip()
        if not name:
            continue
        key = normalize(name)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)


def load_units_cache(path: str | Path | None) -> dict[str, Any] | None:
    """读取 units_site.json；损坏/缺失返回 None。"""

    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    units = payload.get("unitObject")
    if not isinstance(units, dict) or not units:
        return None
    return payload


def fetch_units_page(
    cache_path: str | Path | None = None,
    timeout: float = 20.0,
    url: str = UNITS_URL,
) -> dict[str, Any]:
    """抓取 pcrdfans /units 的 __NEXT_DATA__。

    成功时把 unitObject / cn / us（含 fetched_at）缓存到 cache_path；
    网络或解析失败时回退到缓存，并标记 cache_used=True；没有缓存才抛错。
    """

    try:
        request = urllib.request.Request(
            url,
            headers={
                "user-agent": USER_AGENT,
                "accept": "text/html,application/xhtml+xml",
                "referer": "https://pcrdfans.com/",
            },
        )
        with urllib.request.urlopen(request, timeout=max(5.0, float(timeout))) as response:
            html = response.read().decode("utf-8", "replace")
        match = re.search(
            r"<script[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
            html,
            re.DOTALL,
        )
        if not match:
            raise ValueError("页面里没有 __NEXT_DATA__")
        data = json.loads(match.group(1))
        server = data["props"]["initialState"]["server"]
        units = server.get("unitObject")
        if not isinstance(units, dict) or not units:
            raise ValueError("unitObject 为空")
        result = {
            "source": url,
            "fetched_at": _now_iso(),
            "server": int(server.get("server") or 1),
            "cn": [int(value) for value in (server.get("cn") or [])],
            "us": [int(value) for value in (server.get("us") or [])],
            "unitObject": {str(key): value for key, value in units.items()},
        }
        if cache_path:
            _write_json(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        cached = load_units_cache(cache_path)
        if cached is not None:
            cached = dict(cached)
            cached["cache_used"] = True
            cached["cache_error"] = f"{type(exc).__name__}: {exc}"
            return cached
        raise RuntimeError(f"抓取 pcrdfans /units 失败，且没有本地缓存：{exc}") from exc


def load_aliases_extra(path: str | Path | None) -> dict[int, list[str]]:
    """读取 aliases_extra.json，键支持 4 位 uid4 或 6 位 unit id。"""

    if not path:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[int, list[str]] = {}
    for raw_key, raw_value in raw.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            continue
        if isinstance(raw_value, str):
            values = [part for part in re.split(r"[\s,，、]+", raw_value) if part]
        elif isinstance(raw_value, (list, tuple, set)):
            values = [str(value) for value in raw_value]
        else:
            continue
        clean = _clean_names(values)
        if not clean:
            continue
        keys = [key]
        if key >= 100000:
            keys.append(key // 100)
        else:
            keys.append(key * 100 + 1)
        for item in keys:
            bucket = result.setdefault(item, [])
            for name in clean:
                if name not in bucket:
                    bucket.append(name)
    return result


def build_characters(updated_at: str | None = None) -> dict[str, Any]:
    """仅用内置 CHARA_NAME 的兜底数据（抓不到 /units 时使用）。"""

    characters: list[dict[str, Any]] = []
    for raw_id, raw_names in CHARA_NAME.items():
        try:
            uid4 = int(raw_id)
        except (TypeError, ValueError):
            continue
        if uid4 <= 1000 or uid4 in UNAVAILABLE_CHARA:
            continue
        names = _clean_names(raw_names)
        if not names:
            continue
        name_jp = next(
            (alias for alias in names if any("\u3040" <= ch <= "\u30ff" for ch in alias)),
            "",
        )
        characters.append(
            {
                "id": uid4 * 100 + 1,
                "uid4": uid4,
                "name": names[0],
                "name_jp": name_jp,
                "name_lang": "zh",
                "name_source": "local",
                "aliases": names[1:],
                "servers": [],
            }
        )

    characters.sort(key=lambda item: item["id"])
    return {
        "schema": DATA_SCHEMA,
        "source": "local_fallback",
        "updated_at": updated_at or "",
        "count": len(characters),
        "stats": {
            "cn": 0,
            "us": 0,
            "zh": len(characters),
            "ja_only": 0,
        },
        "characters": characters,
    }


def build_characters_from_units(
    units_payload: Mapping[str, Any],
    *,
    aliases_extra: Mapping[int, Iterable[str]] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """把 /units 的 351 个单位与本地中文名 / 别称合并。"""

    unit_object = units_payload.get("unitObject")
    if not isinstance(unit_object, Mapping) or not unit_object:
        raise ValueError("units_payload 缺少 unitObject")
    cn_ids = {int(value) for value in (units_payload.get("cn") or [])}
    us_ids = {int(value) for value in (units_payload.get("us") or [])}
    extras = aliases_extra or {}

    characters: list[dict[str, Any]] = []
    for raw in unit_object.values():
        if not isinstance(raw, Mapping):
            continue
        try:
            unit_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        uid4 = unit_id // 100 if unit_id >= 100000 else unit_id
        unit_name = str(raw.get("name") or "").strip()
        local_names = _clean_names(CHARA_NAME.get(str(uid4), []))
        if local_names:
            name = local_names[0]
            name_lang = "zh"
            name_source = "local"
            aliases = local_names[1:]
        else:
            name = unit_name or str(uid4)
            name_lang = "ja"
            name_source = "units_site"
            aliases = []

        candidates: list[Any] = list(aliases)
        if unit_name and unit_name != name:
            candidates.append(unit_name)
        candidates.extend(extras.get(unit_id, []))
        candidates.extend(extras.get(uid4, []))
        aliases = [
            item
            for item in _clean_names(candidates)
            if normalize(item) != normalize(name)
        ]

        servers: list[str] = []
        if unit_id in cn_ids:
            servers.append("cn")
        if unit_id in us_ids:
            servers.append("us")
        characters.append(
            {
                "id": unit_id,
                "uid4": uid4,
                "name": name,
                "name_jp": unit_name,
                "name_lang": name_lang,
                "name_source": name_source,
                "aliases": aliases,
                "servers": servers,
            }
        )

    characters.sort(key=lambda item: item["id"])
    zh = sum(1 for item in characters if item["name_lang"] == "zh")
    ja_only = sum(1 for item in characters if item["name_lang"] == "ja")
    return {
        "schema": DATA_SCHEMA,
        "source": "pcrdfans_units",
        "source_url": units_payload.get("source") or UNITS_URL,
        "units_fetched_at": units_payload.get("fetched_at") or "",
        "updated_at": updated_at or _now_iso(),
        "server": units_payload.get("server", 1),
        "count": len(characters),
        "stats": {
            # cn / us 用页面数组长度（cn 数组里有两个 id 不在 unitObject，
            # 页面仍显示 317，保持一致）。
            "cn": len(cn_ids),
            "us": len(us_ids),
            "zh": zh,
            "ja_only": ja_only,
        },
        "characters": characters,
    }


def write_characters(path: str | Path, updated_at: str | None = None) -> dict[str, Any]:
    """用本地兜底数据原子写入 characters.json。"""

    payload = build_characters(updated_at)
    _write_json(path, payload)
    return payload


def write_characters_from_units(
    path: str | Path,
    units_payload: Mapping[str, Any],
    *,
    aliases_extra: Mapping[int, Iterable[str]] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """用 /units 权威数据原子写入 characters.json。"""

    payload = build_characters_from_units(
        units_payload,
        aliases_extra=aliases_extra,
        updated_at=updated_at,
    )
    _write_json(path, payload)
    return payload


def merge_previous_names(
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
) -> int:
    """把上一版 characters.json 里的中文名与别称补回新版。

    为什么需要：/units 只给 id 与日文名，中文名是从 biligame 抓的。抓取失败
    （断网、站点抽风、模块缺失）时如果直接覆盖写，中文名就会整片退化成日文名。
    这里做「只补不删」：新版缺中文名、旧版有，就把旧的搬回来；别称取并集。

    返回补回中文名的条数。
    """

    if not previous:
        return 0
    old_chars = previous.get("characters")
    new_chars = payload.get("characters")
    if not isinstance(old_chars, list) or not isinstance(new_chars, list):
        return 0
    old_by_id: dict[int, dict[str, Any]] = {}
    for item in old_chars:
        if isinstance(item, dict) and item.get("id") is not None:
            old_by_id[int(item["id"])] = item

    restored = 0
    for item in new_chars:
        if not isinstance(item, dict):
            continue
        try:
            prev = old_by_id.get(int(item.get("id")))
        except (TypeError, ValueError):
            continue
        if not prev:
            continue
        if item.get("name_lang") != "zh" and prev.get("name_lang") == "zh" and prev.get("name"):
            item["name"] = prev["name"]
            item["name_lang"] = "zh"
            item["name_source"] = prev.get("name_source") or "previous"
            restored += 1
        aliases = [str(a) for a in (item.get("aliases") or []) if str(a).strip()]
        seen = set(aliases)
        for alias in prev.get("aliases") or []:
            text = str(alias).strip()
            if text and text not in seen:
                aliases.append(text)
                seen.add(text)
        if aliases:
            item["aliases"] = aliases
        all_names = [str(n) for n in (item.get("all_names") or []) if str(n).strip()]
        if not all_names:
            names = [item.get("name") or "", item.get("name_jp") or ""] + aliases
            item["all_names"] = [n for n in dict.fromkeys(names) if n]
    stats = payload.get("stats")
    if isinstance(stats, dict) and new_chars:
        stats["zh"] = sum(1 for c in new_chars if isinstance(c, dict) and c.get("name_lang") == "zh")
        stats["ja_only"] = sum(1 for c in new_chars if isinstance(c, dict) and c.get("name_lang") != "zh")
    return restored


def load_characters(path: str | Path) -> dict[str, Any] | None:
    """读取 characters.json；文件缺失或损坏时返回 None。"""

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    chars = payload.get("characters")
    if not isinstance(chars, list) or not chars:
        return None
    # 简单校验，避免把半个损坏文件当成有效库。
    for item in chars:
        if not isinstance(item, dict):
            return None
        try:
            int(item.get("id"))
        except (TypeError, ValueError):
            return None
        if not isinstance(item.get("name"), str):
            return None
    return payload


def ensure_characters(
    path: str | Path,
    updated_at: str | None = None,
    *,
    units_cache_path: str | Path | None = None,
    aliases_extra_path: str | Path | None = None,
) -> dict[str, Any]:
    """确保 characters.json 存在，并优先用 /units 缓存重建。"""

    payload = load_characters(path)
    units = load_units_cache(units_cache_path)
    if units is not None:
        return write_characters_from_units(
            path,
            units,
            aliases_extra=load_aliases_extra(aliases_extra_path),
            updated_at=updated_at or _now_iso(),
        )
    if payload is not None:
        return payload
    return write_characters(path, updated_at)


def edit_distance(left: str, right: str) -> int:
    """Levenshtein 距离（只用于短角色名，纯 Python 足够）。"""

    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_char in enumerate(right, 1):
        current = [row]
        for col, left_char in enumerate(left, 1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[col] + 1,
                    current[col - 1] + 1,
                    previous[col - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    longest = max(len(left), len(right))
    return max(0.0, 1.0 - edit_distance(left, right) / longest)


@dataclass(slots=True)
class Character:
    id: int
    uid4: int
    name: str
    aliases: list[str] = field(default_factory=list)
    all_names: list[str] = field(default_factory=list)
    name_jp: str = ""
    name_lang: str = "zh"
    name_source: str = "local"
    servers: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name + ("*" if self.name_lang == "ja" else "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid4": self.uid4,
            "name": self.name,
            "name_jp": self.name_jp,
            "name_lang": self.name_lang,
            "name_source": self.name_source,
            "aliases": list(self.aliases),
            "all_names": list(self.all_names),
            "servers": list(self.servers),
        }


@dataclass(slots=True)
class ParseResult:
    ids: list[int]
    unknown: list[str]
    tokens: list[str]
    truncated: bool = False


@dataclass(slots=True)
class SearchHit:
    character: Character
    score: float
    matched_alias: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.character.id,
            "name": self.character.name,
            "alias": self.matched_alias,
            "score": round(self.score, 2),
        }


class CharacterIndex:
    """角色 id / 原名 / 别称索引。"""

    def __init__(self, payload: Mapping[str, Any] | Iterable[Mapping[str, Any]]):
        raw_chars: Iterable[Mapping[str, Any]]
        if isinstance(payload, Mapping):
            raw_chars = payload.get("characters", [])  # type: ignore[assignment]
        else:
            raw_chars = payload

        self.characters: list[Character] = []
        self.by_id: dict[int, Character] = {}
        self.by_uid4: dict[int, Character] = {}
        self.stats: dict[str, int] = {}
        if isinstance(payload, Mapping) and isinstance(payload.get("stats"), Mapping):
            self.stats = {
                str(key): int(value)
                for key, value in payload["stats"].items()  # type: ignore[index]
                if isinstance(value, (int, float, str))
            }
        self._alias_map: dict[str, list[int]] = {}
        self._alias_display: dict[str, str] = {}
        self._max_alias_len = 1

        for item in raw_chars:
            try:
                char_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            try:
                uid4 = int(item.get("uid4") or (char_id // 100 if char_id >= 100000 else char_id))
            except (TypeError, ValueError):
                uid4 = char_id // 100 if char_id >= 100000 else char_id
            name_jp = str(item.get("name_jp") or "").strip()
            name_lang = str(item.get("name_lang") or ("zh" if name else "ja"))
            name_source = str(item.get("name_source") or "local")
            raw_servers = item.get("servers")
            servers = [
                str(server)
                for server in (raw_servers if isinstance(raw_servers, list) else [])
                if server in {"cn", "us"}
            ]
            aliases = [
                str(alias).strip()
                for alias in item.get("aliases", [])
                if str(alias).strip()
            ]
            all_names = _clean_names([name, name_jp, *aliases])
            character = Character(
                id=char_id,
                uid4=uid4,
                name=name,
                aliases=[value for value in all_names if value != name],
                all_names=all_names,
                name_jp=name_jp,
                name_lang=name_lang,
                name_source=name_source,
                servers=servers,
            )
            self.characters.append(character)
            self.by_id[char_id] = character
            self.by_uid4[uid4] = character
            for alias in all_names:
                key = normalize(alias)
                if not key:
                    continue
                self._alias_map.setdefault(key, []).append(char_id)
                self._alias_display.setdefault(key, alias)
                self._max_alias_len = max(self._max_alias_len, len(key))

        self.characters.sort(key=lambda item: item.id)
        # 保证同一别称有多个角色时，优先选择 id 较小的角色，行为可预测。
        for key, ids in self._alias_map.items():
            self._alias_map[key] = sorted(set(ids))

    def __len__(self) -> int:
        return len(self.characters)

    def name(self, char_id: int | str) -> str:
        character = self.character(char_id)
        return character.name if character else str(char_id)

    def display_name(self, char_id: int | str) -> str:
        character = self.character(char_id)
        return character.display_name if character else str(char_id)

    def character(self, char_id: int | str) -> Character | None:
        try:
            cid = int(char_id)
        except (TypeError, ValueError):
            return None
        return self.by_id.get(cid) or self.by_uid4.get(cid)

    def canonical_id(self, char_id: int | str) -> int:
        character = self.character(char_id)
        if character is not None:
            return character.id
        try:
            return int(char_id)
        except (TypeError, ValueError):
            return 0

    def filter_ids(self, char_ids: Iterable[int], region: int) -> list[int]:
        """按 region 过滤：1=cn，2=us，0/其它=全部（日服也走全部）。"""

        if region not in (1, 2):
            return [self.canonical_id(value) for value in char_ids]
        wanted = "cn" if region == 1 else "us"
        filtered: list[int] = []
        for value in char_ids:
            character = self.character(value)
            if character is None:
                continue
            # 本地兜底数据没有 servers 字段，不过滤，避免旧数据全被挡掉。
            if wanted in character.servers or not character.servers:
                filtered.append(character.id)
        return filtered

    def server_counts(self) -> dict[str, int]:
        return {
            "all": len(self.characters),
            "cn": int(self.stats.get("cn") or sum(
                1 for item in self.characters if "cn" in item.servers
            )),
            "us": int(self.stats.get("us") or sum(
                1 for item in self.characters if "us" in item.servers
            )),
            "zh": int(self.stats.get("zh") or sum(
                1 for item in self.characters if item.name_lang == "zh"
            )),
            "ja_only": int(self.stats.get("ja_only") or sum(
                1 for item in self.characters if item.name_lang == "ja"
            )),
        }

    def aliases(self, char_id: int | str) -> list[str]:
        character = self.character(char_id)
        return list(character.aliases) if character else []

    def _id_from_token(self, token: str) -> int | None:
        value = unicodedata.normalize("NFKC", token).strip()
        match = _ID_RE.fullmatch(value)
        if not match:
            return None
        digits = match.group(1)
        number = int(digits)
        if len(digits) == 6:
            character = self.by_id.get(number)
            if character is not None:
                return character.id
            # 也接受 100711 这种具体头像 id，回退到同一角色。
            character = self.by_uid4.get(number // 100)
            return character.id if character is not None else None
        character = self.by_uid4.get(number)
        return character.id if character is not None else None

    def resolve_token(self, token: str) -> int | None:
        """把一个角色名 / 别称 / 4 位或 6 位 id 解析成 6 位 id。"""

        raw = str(token or "").strip()
        if not raw:
            return None
        by_id = self._id_from_token(raw)
        if by_id is not None:
            return by_id
        key = normalize(raw)
        if not key:
            return None

        exact = self._alias_map.get(key)
        if exact:
            return exact[0]

        # 前缀 / 子串匹配：只接受足够长的输入，避免一个“克”字乱命中。
        if len(key) >= 2:
            prefix_hits: list[tuple[int, int]] = []
            substring_hits: list[tuple[int, int]] = []
            for alias, ids in self._alias_map.items():
                if len(alias) < 2:
                    continue
                if alias.startswith(key):
                    prefix_hits.append((len(alias) - len(key), ids[0]))
                elif key in alias:
                    substring_hits.append((len(alias) - len(key), ids[0]))
            if prefix_hits:
                prefix_hits.sort(key=lambda item: (item[0], item[1]))
                return prefix_hits[0][1]
            if substring_hits:
                substring_hits.sort(key=lambda item: (item[0], item[1]))
                return substring_hits[0][1]
        return None

    def segment_token(self, token: str) -> list[int]:
        """把“布丁克总”这种没分隔符的串按已知别称切开。

        只有在能完整切成至少两个角色时才返回，避免把错别字硬拆。
        """

        text = normalize(token)
        if len(text) < 4:
            return []
        memo: dict[int, list[int] | None] = {}

        def walk(pos: int) -> list[int] | None:
            if pos == len(text):
                return []
            if pos in memo:
                return memo[pos]
            upper = min(len(text), pos + self._max_alias_len)
            # 从长到短，优先匹配更长的别称。
            for end in range(upper, pos + 1, -1):
                piece = text[pos:end]
                if len(piece) < 2:
                    continue
                ids = self._alias_map.get(piece)
                if not ids:
                    continue
                rest = walk(end)
                if rest is not None:
                    result = [ids[0], *rest]
                    memo[pos] = result
                    return result
            memo[pos] = None
            return None

        result = walk(0)
        if result and len(result) >= 2:
            return result
        return []

    def parse_text(self, text: str, limit: int = 5) -> ParseResult:
        """解析用户输入的角色串。"""

        tokens = [part for part in _SPLIT_RE.split(str(text or "").strip()) if part]
        ids: list[int] = []
        unknown: list[str] = []
        for token in tokens:
            char_id = self.resolve_token(token)
            if char_id is None:
                segmented = self.segment_token(token)
                if segmented:
                    ids.extend(segmented)
                else:
                    unknown.append(token)
            else:
                ids.append(char_id)

        deduped: list[int] = []
        seen: set[int] = set()
        for char_id in ids:
            if char_id in seen:
                continue
            seen.add(char_id)
            deduped.append(char_id)

        truncated = len(deduped) > max(1, limit)
        if truncated:
            deduped = deduped[: max(1, limit)]
        return ParseResult(
            ids=deduped,
            unknown=unknown,
            tokens=tokens,
            truncated=truncated,
        )

    def _score_keyword(self, key: str, alias: str) -> float:
        if not key or not alias:
            return 0.0
        if alias == key:
            return 100.0
        if alias.startswith(key):
            return 88.0 - min(12.0, len(alias) - len(key))
        if key in alias:
            return 74.0 - min(10.0, len(alias) - len(key))
        if len(key) >= 2 and alias in key:
            return 62.0 - min(8.0, len(key) - len(alias))
        ratio = similarity(key, alias)
        if ratio >= 0.6:
            return ratio * 58.0
        return 0.0

    def search(self, keyword: str, limit: int = 5) -> list[SearchHit]:
        key = normalize(keyword)
        if not key:
            return []
        direct_id = self._id_from_token(str(keyword))
        if direct_id is not None:
            character = self.by_id[direct_id]
            return [
                SearchHit(
                    character=character,
                    score=100.0,
                    matched_alias=str(direct_id),
                )
            ]
        hits: list[SearchHit] = []
        for character in self.characters:
            best_score = 0.0
            best_alias = character.name
            for alias in character.all_names:
                score = self._score_keyword(key, normalize(alias))
                if score > best_score:
                    best_score = score
                    best_alias = alias
            if best_score > 0:
                hits.append(
                    SearchHit(
                        character=character,
                        score=best_score,
                        matched_alias=best_alias,
                    )
                )
        hits.sort(key=lambda item: (-item.score, item.character.id))
        return hits[: max(1, limit)]

    def suggest(self, token: str, limit: int = 3) -> list[SearchHit]:
        """给认不出的词返回最接近的角色候选（编辑距离 / 前缀）。"""

        key = normalize(token)
        if not key:
            return []
        direct_id = self._id_from_token(str(token))
        if direct_id is not None:
            character = self.by_id[direct_id]
            return [
                SearchHit(
                    character=character,
                    score=100.0,
                    matched_alias=str(direct_id),
                )
            ]
        hits: list[SearchHit] = []
        for character in self.characters:
            best_score = 0.0
            best_alias = character.name
            for alias in character.all_names:
                alias_key = normalize(alias)
                if not alias_key:
                    continue
                if alias_key.startswith(key):
                    score = 90.0 - min(20.0, len(alias_key) - len(key))
                elif key in alias_key:
                    score = 70.0 - min(15.0, len(alias_key) - len(key))
                else:
                    score = similarity(key, alias_key) * 65.0
                if score > best_score:
                    best_score = score
                    best_alias = alias
            if best_score > 0:
                hits.append(
                    SearchHit(
                        character=character,
                        score=best_score,
                        matched_alias=best_alias,
                    )
                )
        hits.sort(key=lambda item: (-item.score, item.character.id))
        return hits[: max(1, limit)]


def build_index(payload: Mapping[str, Any] | None = None) -> CharacterIndex:
    if payload is None:
        payload = build_characters()
    return CharacterIndex(payload)
