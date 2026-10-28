// Optional pt-BR names (Jambô terminology) through the Babele module.
Hooks.once("babele.init", (babele) => {
  babele.register({ module: "expanse-age-compendium", lang: "pt-BR", dir: "lang/babele/pt-BR" });
});
