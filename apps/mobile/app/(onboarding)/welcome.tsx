/**
 * Welcome (mobile#142): a race-photo hero, the race team as six specialists,
 * how a Race Mission runs, and the sports STREM prepares for. One action.
 */

import { useRouter } from "expo-router";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon, type IconName } from "@/components/ui/icon";
import { Button, Overline, Row, Wordmark, useLayout, useWindowSize } from "@/components/ui/kit";
import { HeroMedia } from "@/components/ui/photo";
import { C, LAYER_COLOR, R, disp, ui } from "@/constants/theme";
import type { CoverMedia } from "@/lib/api/race-missions";
import { routeForScreen } from "@/lib/onboarding";
import { SPORTS } from "@/lib/race/sports";

/** Openly licensed (CC BY-SA 4.0), credited on the photo. */
const HERO: CoverMedia = {
  url: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/Tomas_Petrecek_-_Running_-_Jeseniky_mountains_2017.jpg/1280px-Tomas_Petrecek_-_Running_-_Jeseniky_mountains_2017.jpg",
  title: "Trail running in the Jeseníky mountains",
  creator: "Romanterik",
  license: "CC BY-SA 4.0",
  license_url: "https://creativecommons.org/licenses/by-sa/4.0",
  source_url: "https://commons.wikimedia.org/wiki/File:Tomas_Petrecek_-_Running_-_Jeseniky_mountains_2017.jpg",
  provider: "wikimedia",
  depicts: "atmosphere",
};

const TEAM: { icon: IconName; color: string; role: string; does: string }[] = [
  { icon: "calendar", color: LAYER_COLOR.training, role: "Coach", does: "Your weeks to the start line, moved when life happens" },
  { icon: "drop", color: LAYER_COLOR.fuel, role: "Fuel", does: "Carbs, fluid and salt per hour, rehearsed in training" },
  { icon: "mountain", color: LAYER_COLOR.course, role: "Course", does: "Climbs, descents and checkpoints, leg by leg" },
  { icon: "pack", color: LAYER_COLOR.gear, role: "Gear", does: "Mandatory kit, tested before race day" },
  { icon: "map", color: LAYER_COLOR.logistics, role: "Logistics", does: "Travel, race week and race morning" },
  { icon: "compass", color: LAYER_COLOR.strategy, role: "Strategy", does: "Pacing, cutoffs and plan B" },
];

const STEPS = [
  { title: "Tell us your race", body: "Distance, climbing, date — or import it." },
  { title: "Prepare every layer", body: "Training, fuel, gear and logistics in one plan." },
  { title: "Race, then debrief", body: "What you learn shapes the next one." },
];

export default function WelcomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { height } = useWindowSize();
  const { wide } = useLayout();
  const pad = wide ? 40 : 20;
  const start = () => router.push(routeForScreen("identity"));

  return (
    <View style={styles.root}>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 120 }} showsVerticalScrollIndicator={false}>
        <HeroMedia
          cover={HERO}
          height={Math.max(440, Math.min(height * 0.66, 640))}
          overlayTop={
            <View style={{ paddingTop: insets.top + 16, paddingHorizontal: pad }}>
              <Wordmark size={15} />
            </View>
          }
        >
          <View style={[styles.inner, { paddingHorizontal: pad, paddingBottom: 28, gap: 12 }]}>
            <View style={styles.pill}>
              <Icon name="sparkles" size={13} color={C.accent} />
              <Text style={[ui(12, 700), { color: C.text }]}>Your AI race team</Text>
            </View>
            <Text accessibilityRole="header" style={[disp(wide ? 68 : 46, 800), { color: C.text, lineHeight: wide ? 70 : 48 }]}>
              Your race.{"\n"}Every layer handled.
            </Text>
            <Text style={[ui(17, 500), { color: C.textMuted, lineHeight: 25, maxWidth: 560 }]}>
              STREM turns your training, races and life into one plan for race day — and keeps it honest every week.
            </Text>
          </View>
        </HeroMedia>

        <View style={[styles.inner, { paddingHorizontal: pad, gap: 32, marginTop: 8 }]}>
          <View style={{ gap: 14 }}>
            <Overline>Meet your race team</Overline>
            <View style={styles.team}>
              {TEAM.map((m) => (
                <View key={m.role} style={[styles.member, { width: wide ? "31.5%" : "48%" }]}>
                  <View style={[styles.avatar, { backgroundColor: `${m.color}24`, borderColor: `${m.color}66` }]}>
                    <Icon name={m.icon} size={20} color={m.color} />
                  </View>
                  <Text style={[ui(15, 700), { color: C.text }]}>{m.role}</Text>
                  <Text style={[ui(12.5, 500), { color: C.textMuted, lineHeight: 18 }]}>{m.does}</Text>
                </View>
              ))}
            </View>
          </View>

          <View style={{ gap: 14 }}>
            <Overline>How a Race Mission runs</Overline>
            <View style={{ gap: 0 }}>
              {STEPS.map((s, i) => (
                <Row key={s.title} gap={14} align="flex-start">
                  <View style={{ alignItems: "center" }}>
                    <View style={styles.step}>
                      <Text style={[ui(14, 800), { color: C.accentInk }]}>{i + 1}</Text>
                    </View>
                    {i < STEPS.length - 1 ? <View style={styles.rail} /> : null}
                  </View>
                  <View style={{ flex: 1, gap: 2, paddingTop: 4, paddingBottom: 18 }}>
                    <Text style={[ui(16, 700), { color: C.text }]}>{s.title}</Text>
                    <Text style={[ui(14, 500), { color: C.textMuted }]}>{s.body}</Text>
                  </View>
                </Row>
              ))}
            </View>
          </View>

          <View style={{ gap: 12 }}>
            <Overline>Built for the hard ones</Overline>
            <View style={styles.sports}>
              {SPORTS.filter((s) => s.id !== "custom").map((s) => (
                <View key={s.id} style={styles.sport}>
                  <Icon name={s.icon} size={15} color={C.textMuted} />
                  <Text style={[ui(13, 600), { color: C.text }]}>{s.short}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>
      </ScrollView>

      <View style={[styles.dock, { paddingBottom: insets.bottom + 16, paddingHorizontal: pad }]}>
        <View style={[styles.inner, { gap: 8 }]}>
          <Button label="Get started" iconRight="chevron" size="lg" full onPress={start} />
          <Text style={[ui(12, 500), { color: C.textDim, textAlign: "center" }]}>About two minutes · change anything later</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.ink },
  inner: { width: "100%", maxWidth: 760, alignSelf: "center" },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: C.glass, borderWidth: 1, borderColor: C.lineStrong },
  team: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", rowGap: 10 },
  member: { gap: 6, padding: 14, borderRadius: R.md, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", borderWidth: 1, marginBottom: 4 },
  step: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: C.accent },
  rail: { width: 2, flex: 1, minHeight: 18, backgroundColor: C.accentLine },
  sports: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  sport: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 11, paddingVertical: 7, borderRadius: 999, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  dock: { position: "absolute", left: 0, right: 0, bottom: 0, paddingTop: 14, backgroundColor: C.scrim, borderTopWidth: 1, borderTopColor: C.line },
});
