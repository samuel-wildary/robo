import json

with open('flows/flows.json', 'r', encoding='utf-8') as f:
    flows = json.load(f)

var1 = """Esses são alguns dos benefícios que muitas mulheres relatam ao incluir essa receita na rotina:

✔️ Ajuda no processo de emagrecimento
✔️ Contribui para diminuir o inchaço
✔️ Ajuda a controlar melhor o apetite
✔️ Pode aumentar a disposição no dia a dia
✔️ Pode contribuir para mais leveza e bem-estar
✔️ Ajuda você a se sentir melhor com o próprio corpo
✔️ Pode auxiliar no metabolismo
✔️ Pode trazer mais energia para a rotina

❤ E o melhor: é uma receita simples, natural e fácil de preparar.

🛒 Você encontra os ingredientes com facilidade e sem gastar muito.

Agora me conta uma coisa para eu te ajudar melhor: seu foco é emagrecer, perder barriga ou diminuir o inchaço?"""

var2 = """Olha só alguns dos benefícios dessa receita:

✔️ Ajuda no emagrecimento
✔️ Reduz o inchaço
✔️ Ajuda no controle da fome
✔️ Traz mais disposição
✔️ Pode melhorar sua autoestima
✔️ Ajuda a acelerar a rotina do metabolismo
✔️ Pode contribuir para você se sentir mais leve no dia a dia

❤ Por ser uma receita simples e natural, muita gente gosta justamente pela praticidade.

🛒 Os ingredientes são baratos e fáceis de encontrar.

Me fala aqui: você quer perder quantos quilos ou seu maior incômodo hoje é a barriga?"""

var3 = """Deixa eu te mostrar por que tanta gente tem se interessado por essa receita:

✔️ Ajuda a emagrecer
✔️ Ajuda a reduzir o inchaço
✔️ Pode dar mais disposição
✔️ Ajuda a controlar melhor a vontade de comer
✔️ Pode contribuir para mais bem-estar
✔️ Ajuda você a se sentir mais leve e confiante

❤ Além disso, é uma receita simples, natural e fácil de fazer.

🛒 Os ingredientes cabem no bolso e você encontra com facilidade.

Agora me conta: hoje você quer mais perder barriga, diminuir o inchaço ou eliminar alguns quilos?"""

for flow in flows['flows']:
    if flow['id'] == 'funil_gelatina':
        actions = flow['steps']['boas_vindas']['actions']
        
        idx = -1
        for i, a in enumerate(actions):
            if a.get('type') == 'text' and 'Esses são os benefícios' in a.get('text', '') and type(a.get('text')) == str:
                idx = i
                break
        
        if idx != -1:
            actions[idx]['text'] = [var1, var2, var3]
            try:
                # Need to pop the next 3 items: computing, wait, text 
                # (but since index shrinks, we just pop at idx + 1 three times)
                for _ in range(3):
                    if idx + 1 < len(actions):
                        actions.pop(idx + 1)
            except IndexError:
                pass

with open('flows/flows.json', 'w', encoding='utf-8') as f:
    json.dump(flows, f, ensure_ascii=False, indent=2)
    f.write('\n')
