//! TR / EN strings. Language from `FAB_LANG`, then `LANG`; default English.

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Lang {
    En,
    Tr,
}

pub fn detect() -> Lang {
    let v = std::env::var("FAB_LANG")
        .or_else(|_| std::env::var("LANG"))
        .unwrap_or_default()
        .to_lowercase();
    if v.starts_with("tr") {
        Lang::Tr
    } else {
        Lang::En
    }
}

pub struct T {
    pub role: &'static str,
    pub reports_to: &'static str,
    pub team: &'static str,
    pub people: &'static str,
    pub agents: &'static str,
    pub recurring: &'static str,
    pub recent_runs: &'static str,
    pub files: &'static str,
    pub agent_pane: &'static str,
    pub agent_pane_hint: &'static str,
    pub no_files: &'static str,
    pub keys_sidebar: &'static str,
    pub keys_agent: &'static str,
    pub ended: &'static str,
    pub loading_failed: &'static str,
    pub empty: &'static str,
}

pub fn strings(l: Lang) -> T {
    match l {
        Lang::En => T {
            role: "Role",
            reports_to: "Reports to",
            team: "Team",
            people: "people",
            agents: "agents",
            recurring: "Recurring",
            recent_runs: "Recent runs",
            files: "Files",
            agent_pane: "Agent session",
            agent_pane_hint: "The agent session attaches here once your workspace is provisioned (ADR-0014, follow-up 2).",
            no_files: "no files yet",
            keys_sidebar: " r refresh · Enter/Tab/Ctrl+O agent · q quit ",
            keys_agent: " Ctrl+O sidebar (then q to quit) ",
            ended: "ended — Enter to restart",
            loading_failed: "Could not load",
            empty: "nothing yet",
        },
        Lang::Tr => T {
            role: "Rol",
            reports_to: "Bağlı olduğu",
            team: "Ekip",
            people: "kişi",
            agents: "ajan",
            recurring: "Tekrarlayan",
            recent_runs: "Son çalışmalar",
            files: "Dosyalar",
            agent_pane: "Ajan oturumu",
            agent_pane_hint: "Çalışma alanınız hazır olduğunda ajan oturumu burada açılır (ADR-0014, takip 2).",
            no_files: "henüz dosya yok",
            keys_sidebar: " r yenile · Enter/Tab/Ctrl+O ajan · q çıkış ",
            keys_agent: " Ctrl+O kenar çubuğu (sonra q ile çıkış) ",
            ended: "bitti — yeniden başlatmak için Enter",
            loading_failed: "Yüklenemedi",
            empty: "henüz yok",
        },
    }
}
