//! Plain-text table formatting. Functions return `String`s (instead of
//! printing directly) so they could be unit-tested or written to a file.

use std::fmt::Write as _; // brings `write!`/`writeln!` for `String` into scope

use hoops_core::analysis::add_impact::{AddDropImpact, CategoryRecord, Outcome};
use hoops_core::analysis::available::AvailablePlayer;
use hoops_core::analysis::suggest::Suggestion;
use hoops_core::analysis::team_report::TeamReport;
use hoops_core::{Category, LeagueData, StatLine, Team};

/// Format one category value: percentages as .xxx, counts with one decimal.
fn fmt_value(cat: Category, v: f64) -> String {
    if cat.is_percentage() {
        format!("{v:.3}")
    } else {
        format!("{v:.1}")
    }
}

fn cat_header(out: &mut String) {
    for cat in Category::ALL {
        let _ = write!(out, "{:>6}", cat.abbrev());
    }
}

fn stat_cells(out: &mut String, s: &StatLine) {
    for cat in Category::ALL {
        let _ = write!(out, "{:>6}", fmt_value(cat, s.value(cat)));
    }
}

fn player_name(data: &LeagueData, key: &str) -> String {
    data.player(key)
        .map_or_else(|| key.to_string(), |p| p.name.clone())
}

pub fn available_table(rows: &[AvailablePlayer<'_>], sort_label: &str) -> String {
    let mut out = String::new();
    // `write!` into a String cannot fail, so ignoring the Result is fine.
    let _ = write!(
        out,
        "{:>3}  {:<24}{:<5}{:<7}{:>3}",
        "#", "Player", "Team", "Pos", "GP"
    );
    cat_header(&mut out);
    let _ = writeln!(out, "{sort_label:>9}");
    for (i, r) in rows.iter().enumerate() {
        let p = r.player;
        let _ = write!(
            out,
            "{:>3}  {:<24}{:<5}{:<7}{:>3}",
            i + 1,
            p.name,
            p.nba_team,
            p.positions.join("/"),
            p.season.gp
        );
        stat_cells(&mut out, &r.per_game);
        let _ = writeln!(out, "{:>9.2}", r.score);
    }
    out
}

pub fn team_report(r: &TeamReport) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "Team report: {} — week {} (per-game roster strength, ranked 1-{})\n",
        r.team.name, r.week, r.num_teams
    );
    let _ = writeln!(
        out,
        "{:<6}{:>9}{:>7}{:>10}{:>10}  Note",
        "Cat", "Value", "Rank", "LgAvg", "LgBest"
    );
    for row in &r.rows {
        let c = row.category;
        let _ = writeln!(
            out,
            "{:<6}{:>9}{:>7}{:>10}{:>10}  {}{}",
            c.abbrev(),
            fmt_value(c, row.value),
            format!("{}/{}", row.rank, r.num_teams),
            fmt_value(c, row.league_avg),
            fmt_value(c, row.league_best),
            row.strength.label(),
            if c.lower_is_better() {
                " (lower is better)"
            } else {
                ""
            }
        );
    }
    let weak: Vec<_> = r.weak_categories().iter().map(|c| c.abbrev()).collect();
    let _ = writeln!(out, "\nAverage category rank: {:.2}", r.average_rank());
    let _ = writeln!(
        out,
        "Weak categories: {}",
        if weak.is_empty() {
            "none".to_string()
        } else {
            weak.join(", ")
        }
    );
    out
}

pub fn league_rank_grid(data: &LeagueData, r: &TeamReport) -> String {
    let mut out = String::new();
    let _ = write!(out, "{:<24}", "League ranks");
    cat_header(&mut out);
    let _ = writeln!(out, "{:>7}", "Avg");
    let mut standings: Vec<_> = r.standings.iter().collect();
    let avg = |s: &&hoops_core::analysis::team_report::TeamStanding| {
        s.ranks.iter().map(|(_, &rk)| f64::from(rk)).sum::<f64>() / 9.0
    };
    standings.sort_by(|a, b| avg(a).total_cmp(&avg(b)));
    for s in standings {
        let name = data
            .team(&s.team_key)
            .map_or(s.team_key.as_str(), |t| t.name.as_str());
        let marker = if s.team_key == r.team.team_key {
            "*"
        } else {
            " "
        };
        let _ = write!(out, "{marker}{name:<23}");
        for (_, rank) in s.ranks.iter() {
            let _ = write!(out, "{rank:>6}");
        }
        let _ = writeln!(out, "{:>7.2}", avg(&s));
    }
    out
}

pub fn add_impact(data: &LeagueData, team: &Team, i: &AddDropImpact) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "Add/drop impact: {} — week {}\n", team.name, i.week);
    let _ = writeln!(out, "Adds used: {}/{}", i.adds.len(), i.adds_limit);
    let names = |keys: &[String]| -> String {
        if keys.is_empty() {
            "none".into()
        } else {
            keys.iter()
                .map(|k| player_name(data, k))
                .collect::<Vec<_>>()
                .join(", ")
        }
    };
    let _ = writeln!(out, "  Added:   {}", names(&i.adds));
    let _ = writeln!(out, "  Dropped: {}\n", names(&i.drops));

    let _ = write!(out, "{:<16}", "Weekly totals");
    cat_header(&mut out);
    let _ = writeln!(out);
    let _ = write!(out, "{:<16}", "Actual");
    stat_cells(&mut out, &i.actual);
    let _ = writeln!(out);
    let _ = write!(out, "{:<16}", "Without moves");
    stat_cells(&mut out, &i.without_moves);
    let _ = writeln!(out);

    if let (Some((opp_key, opp)), Some((actual, without))) = (&i.opponent, i.records()) {
        let _ = write!(out, "{:<16}", "Opponent");
        stat_cells(&mut out, opp);
        let _ = writeln!(out);
        let sym = |o: Outcome| match o {
            Outcome::Win => "W",
            Outcome::Loss => "L",
            Outcome::Tie => "T",
        };
        for (label, rec) in [("Result actual", &actual), ("Result w/o", &without)] {
            let _ = write!(out, "{label:<16}");
            for (_, o) in rec.per_category.iter() {
                let _ = write!(out, "{:>6}", sym(*o));
            }
            let _ = writeln!(out, "   {}-{}-{}", rec.wins, rec.losses, rec.ties);
        }
        let opp_name = data
            .team(opp_key)
            .map_or(opp_key.as_str(), |t| t.name.as_str());
        let rec = |r: &CategoryRecord| format!("{}-{}-{}", r.wins, r.losses, r.ties);
        let _ = if i.adds.is_empty() && i.drops.is_empty() {
            writeln!(
                out,
                "\nvs {opp_name}: no moves this week ({}).",
                rec(&actual)
            )
        } else if actual == without {
            writeln!(
                out,
                "\nvs {opp_name}: moves did not change the result ({}).",
                rec(&actual)
            )
        } else {
            writeln!(
                out,
                "\nvs {opp_name}: moves changed the matchup from {} to {}.",
                rec(&without),
                rec(&actual)
            )
        };
    } else {
        let _ = writeln!(out, "\nNo matchup found for this week.");
    }
    let _ = writeln!(
        out,
        "Note: weekly stats cover the full week, including games before an add / after a drop."
    );
    out
}

pub fn suggestions(rows: &[Suggestion<'_>], targets: &[Category]) -> String {
    let mut out = String::new();
    let _ = write!(out, "{:>3}  {:<24}{:<7}", "#", "Player", "Pos");
    for c in targets {
        let _ = write!(out, "{:>8}", format!("z{}", c.abbrev()));
    }
    let _ = writeln!(out, "{:>9}{:>8}", "z(9cat)", "Score");
    for (i, s) in rows.iter().enumerate() {
        let _ = write!(
            out,
            "{:>3}  {:<24}{:<7}",
            i + 1,
            s.player.name,
            s.player.positions.join("/")
        );
        for &c in targets {
            let _ = write!(out, "{:>8.2}", s.z[c]);
        }
        let total: f64 = s.z.iter().map(|(_, v)| v).sum();
        let _ = writeln!(out, "{total:>9.2}{:>8.2}", s.score);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentages_get_three_decimals() {
        assert_eq!(fmt_value(Category::FgPct, 0.4567), "0.457");
        assert_eq!(fmt_value(Category::Pts, 12.345), "12.3");
    }
}
