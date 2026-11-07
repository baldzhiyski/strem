/**
 * STREM Race OS UI kit: the shared building blocks of every screen.
 *
 * Hierarchy rule (race-experience-blueprint): identity -> state -> decision ->
 * evidence -> uncertainty -> action. Components here keep one dominant action
 * per view (white primary), recessive chrome, and provenance always visible.
 */

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon, type IconName } from "@/components/ui/icon";
import { C, R, brand, disp, mono, ui } from "@/constants/theme";

export const WIDE = 1024;
export const MEDIUM = 680;

const noSubscription = () => () => {};

/**
 * The window size, safe for the pre-rendered web pages. They are rendered without
 * a window (0 x 0), and the browser's first render must match that HTML or React
 * keeps the server's styles. So the size reads 0 while the page hydrates and is
 * real right after; screens that mount later get the real size straight away.
 */
export function useWindowSize() {
  const size = useWindowDimensions();
  const hydrated = useSyncExternalStore(noSubscription, () => true, () => false);
  return hydrated ? size : { width: 0, height: 0 };
}

export function useLayout() {
  const { width } = useWindowSize();
  return { width, wide: width >= WIDE, medium: width >= MEDIUM };
}

// ── Typography ───────────────────────────────────────────────────────────────

export function Overline({ children, color = C.textMuted, style }: { children: ReactNode; color?: string; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.overline, { color }, style]}>{children}</Text>;
}

export function Title({ children, size = 30, style, numberOfLines }: { children: ReactNode; size?: number; style?: StyleProp<TextStyle>; numberOfLines?: number }) {
  return (
    <Text accessibilityRole="header" numberOfLines={numberOfLines} style={[{ ...disp(size, 800), lineHeight: Math.round(size * 1.08), color: C.text, letterSpacing: 0.2 }, style]}>
      {children}
    </Text>
  );
}

export function Body({ children, muted = false, size = 15, style, numberOfLines }: { children: ReactNode; muted?: boolean; size?: number; style?: StyleProp<TextStyle>; numberOfLines?: number }) {
  return (
    <Text numberOfLines={numberOfLines} style={[{ ...ui(size, 500), lineHeight: Math.round(size * 1.5), color: muted ? C.textMuted : C.text }, style]}>
      {children}
    </Text>
  );
}

export function Data({ children, size = 14, color = C.text, style }: { children: ReactNode; size?: number; color?: string; style?: StyleProp<TextStyle> }) {
  return <Text style={[{ ...mono(size, 700), color }, style]}>{children}</Text>;
}

// ── Layout ───────────────────────────────────────────────────────────────────

export function Row({ children, gap = 10, style, wrap = false, align = "center" }: { children: ReactNode; gap?: number; style?: StyleProp<ViewStyle>; wrap?: boolean; align?: ViewStyle["alignItems"] }) {
  return <View style={[{ flexDirection: "row", alignItems: align, gap, flexWrap: wrap ? "wrap" : "nowrap" }, style]}>{children}</View>;
}

export function Stack({ children, gap = 12, style }: { children: ReactNode; gap?: number; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ gap }, style]}>{children}</View>;
}

/** Scrollable page body with the night canvas, safe-area top and tab-bar room. */
export function Page({
  children,
  header,
  padTop = true,
  maxWidth = 1180,
  bottomRoom = 120,
  contentStyle,
}: {
  children: ReactNode;
  header?: ReactNode;
  padTop?: boolean;
  maxWidth?: number;
  bottomRoom?: number;
  contentStyle?: StyleProp<ViewStyle>;
}) {
  const insets = useSafeAreaInsets();
  const { wide } = useLayout();
  return (
    <ScrollView
      style={styles.page}
      contentContainerStyle={{ paddingBottom: bottomRoom + insets.bottom }}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      {header}
      <View
        style={[
          styles.pageInner,
          { maxWidth, paddingTop: padTop ? insets.top + (wide ? 28 : 16) : 0, paddingHorizontal: wide ? 32 : 18 },
          contentStyle,
        ]}
      >
        {children}
      </View>
    </ScrollView>
  );
}

// ── Surfaces ─────────────────────────────────────────────────────────────────

type CardTone = "default" | "raised" | "outline" | "glass" | "accent" | "flame";

export function Card({ children, tone = "default", pad = 18, style, onPress, accessibilityLabel, testID }: { children: ReactNode; tone?: CardTone; pad?: number; style?: StyleProp<ViewStyle>; onPress?: () => void; accessibilityLabel?: string; testID?: string }) {
  const toneStyle = cardTones[tone];
  if (onPress) {
    return (
      <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={accessibilityLabel} onPress={onPress} style={({ pressed }) => [styles.card, toneStyle, { padding: pad }, pressed && styles.pressed, style]}>
        {children}
      </Pressable>
    );
  }
  return <View testID={testID} style={[styles.card, toneStyle, { padding: pad }, style]}>{children}</View>;
}

const cardTones: Record<CardTone, ViewStyle> = {
  default: { backgroundColor: C.surface, borderColor: C.line },
  raised: { backgroundColor: C.surface2, borderColor: C.lineStrong },
  outline: { backgroundColor: "transparent", borderColor: C.lineStrong },
  glass: { backgroundColor: C.glass, borderColor: C.lineStrong },
  accent: { backgroundColor: "rgba(74,222,128,0.07)", borderColor: C.accentLine },
  flame: { backgroundColor: C.flameSoft, borderColor: "rgba(255,90,78,0.32)" },
};

export function Divider({ style }: { style?: StyleProp<ViewStyle> }) {
  return <View style={[{ height: 1, backgroundColor: C.line }, style]} />;
}

// ── Actions ──────────────────────────────────────────────────────────────────

type ButtonKind = "primary" | "secondary" | "ghost" | "accent" | "danger";

export function Button({
  label,
  onPress,
  kind = "primary",
  icon,
  iconRight,
  loading = false,
  disabled = false,
  size = "md",
  full = false,
  style,
  accessibilityLabel,
}: {
  label: string;
  onPress?: () => void;
  kind?: ButtonKind;
  icon?: IconName;
  iconRight?: IconName;
  loading?: boolean;
  disabled?: boolean;
  size?: "sm" | "md" | "lg";
  full?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const palette = buttonPalette[kind];
  const blocked = disabled || loading;
  const height = size === "lg" ? 56 : size === "sm" ? 40 : 48;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: blocked, busy: loading }}
      disabled={blocked}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { minHeight: Math.max(height, 44), backgroundColor: palette.bg, borderColor: palette.border, paddingHorizontal: size === "sm" ? 14 : 20 },
        full && { alignSelf: "stretch" },
        (pressed || disabled) && { opacity: disabled ? 0.4 : 0.82 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={palette.fg} />
      ) : (
        <>
          {icon ? <Icon name={icon} size={size === "sm" ? 16 : 18} color={palette.fg} sw={2.2} /> : null}
          <Text style={[size === "sm" ? ui(13, 700) : ui(15, 700), { color: palette.fg, letterSpacing: 0.2 }]} numberOfLines={1}>
            {label}
          </Text>
          {iconRight ? <Icon name={iconRight} size={size === "sm" ? 16 : 18} color={palette.fg} sw={2.2} /> : null}
        </>
      )}
    </Pressable>
  );
}

const buttonPalette: Record<ButtonKind, { bg: string; fg: string; border: string }> = {
  primary: { bg: C.white, fg: C.ink, border: C.white },
  secondary: { bg: C.surface2, fg: C.text, border: C.lineStrong },
  ghost: { bg: "transparent", fg: C.text, border: "transparent" },
  accent: { bg: C.accent, fg: C.accentInk, border: C.accent },
  danger: { bg: C.flameSoft, fg: C.flame, border: "rgba(255,90,78,0.4)" },
};

export function IconButton({ icon, onPress, label, size = 44, tone = "glass", color }: { icon: IconName; onPress?: () => void; label: string; size?: number; tone?: "glass" | "surface" | "plain"; color?: string }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [
        { width: size, height: size, borderRadius: size / 2, alignItems: "center", justifyContent: "center" },
        tone === "glass" && { backgroundColor: C.glass, borderWidth: 1, borderColor: C.lineStrong },
        tone === "surface" && { backgroundColor: C.surface2, borderWidth: 1, borderColor: C.line },
        pressed && styles.pressed,
      ]}
    >
      <Icon name={icon} size={Math.round(size * 0.45)} color={color ?? C.text} />
    </Pressable>
  );
}

export function TextLink({ label, onPress, icon = "chevron", color = C.text }: { label: string; onPress: () => void; icon?: IconName; color?: string }) {
  return (
    <Pressable accessibilityRole="link" onPress={onPress} hitSlop={10} style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32 }, pressed && styles.pressed]}>
      <Text style={[ui(13, 700), { color }]}>{label}</Text>
      <Icon name={icon} size={15} color={color} />
    </Pressable>
  );
}

// ── Labels ───────────────────────────────────────────────────────────────────

export function Chip({ label, icon, color = C.textMuted, bg = C.surface2, border = C.line, onPress, selected = false }: { label: string; icon?: IconName; color?: string; bg?: string; border?: string; onPress?: () => void; selected?: boolean }) {
  const content = (
    <>
      {icon ? <Icon name={icon} size={14} color={selected ? C.ink : color} sw={2.2} /> : null}
      <Text style={[ui(12, 700), { color: selected ? C.ink : color }]} numberOfLines={1}>
        {label}
      </Text>
    </>
  );
  const base: StyleProp<ViewStyle> = [styles.chip, { backgroundColor: selected ? C.white : bg, borderColor: selected ? C.white : border }];
  if (onPress) {
    return (
      <Pressable accessibilityRole="button" accessibilityState={{ selected }} onPress={onPress} style={({ pressed }) => [base, { minHeight: 36 }, pressed && styles.pressed]}>
        {content}
      </Pressable>
    );
  }
  return <View style={base}>{content}</View>;
}

export type Origin = "ai" | "engine" | "athlete";

/** Who produced this content. Engine output is never presented as AI. */
export function OriginBadge({ origin, model }: { origin: Origin | null | undefined; model?: string | null }) {
  if (!origin) return null;
  const map = {
    ai: { label: "AI race team", icon: "sparkles" as IconName, color: C.accent, bg: C.accentSoft, border: C.accentLine },
    engine: { label: "Race engine", icon: "sliders" as IconName, color: C.textMuted, bg: C.surface2, border: C.line },
    athlete: { label: "Your plan", icon: "user" as IconName, color: C.text, bg: C.surface2, border: C.line },
  }[origin];
  return (
    <View accessibilityLabel={`${map.label}${model ? ` (${model})` : ""}`} style={[styles.chip, { backgroundColor: map.bg, borderColor: map.border }]}>
      <Icon name={map.icon} size={13} color={map.color} sw={2.2} />
      <Text style={[ui(11, 700), { color: map.color, letterSpacing: 0.3 }]}>{map.label}</Text>
    </View>
  );
}

export type Provenance = "recorded" | "athlete" | "calculated" | "plan" | "official" | "assumption" | "unknown";

export function SourceTag({ source }: { source: Provenance | string }) {
  const label: Record<string, string> = {
    recorded: "Recorded",
    athlete: "You said",
    calculated: "Calculated",
    plan: "Plan",
    official: "Official",
    assumption: "Assumption",
    unknown: "Unknown",
  };
  return (
    <Text style={[mono(10, 700), { color: C.textDim, letterSpacing: 0.6, textTransform: "uppercase" }]}>
      {label[source] ?? source}
    </Text>
  );
}

export type Status = "done" | "partial" | "missed" | "skipped" | "planned" | "rest" | "today" | "attention" | "critical" | "info";

export const STATUS: Record<Status, { icon: IconName; color: string; label: string }> = {
  done: { icon: "checkCircle", color: C.good, label: "Done" },
  partial: { icon: "halfCircle", color: C.warning, label: "Partial" },
  missed: { icon: "xCircle", color: C.serious, label: "No evidence" },
  skipped: { icon: "minus", color: C.textDim, label: "Skipped" },
  planned: { icon: "circle", color: C.textDim, label: "Planned" },
  rest: { icon: "moon", color: C.textDim, label: "Rest" },
  today: { icon: "target", color: C.white, label: "Today" },
  attention: { icon: "alert", color: C.warning, label: "Attention" },
  critical: { icon: "alert", color: C.critical, label: "Critical" },
  info: { icon: "info", color: C.textMuted, label: "Info" },
};

export function StatusLabel({ status, compact = false }: { status: Status; compact?: boolean }) {
  const s = STATUS[status];
  return (
    <Row gap={5}>
      <Icon name={s.icon} size={compact ? 14 : 16} color={s.color} sw={2.2} />
      {compact ? null : <Text style={[ui(12, 700), { color: C.textMuted }]}>{s.label}</Text>}
    </Row>
  );
}

// ── Blocks ───────────────────────────────────────────────────────────────────

export function SectionHeader({ title, overline, action, icon, iconColor }: { title: string; overline?: string; action?: ReactNode; icon?: IconName; iconColor?: string }) {
  return (
    <View style={styles.sectionHeader}>
      <View style={{ flex: 1, gap: 4 }}>
        {overline ? <Overline>{overline}</Overline> : null}
        <Row gap={8}>
          {icon ? <Icon name={icon} size={18} color={iconColor ?? C.text} /> : null}
          <Text accessibilityRole="header" style={[disp(22, 800), { color: C.text, letterSpacing: 0.3 }]}>
            {title}
          </Text>
        </Row>
      </View>
      {action}
    </View>
  );
}

export function StatTile({ label, value, unit, note, style }: { label: string; value: string; unit?: string; note?: string; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.stat, style]}>
      <Text style={[ui(12, 600), { color: C.textMuted }]} numberOfLines={1}>
        {label}
      </Text>
      <Row gap={4} align="flex-end">
        <Text style={[disp(28, 700), { color: C.text, lineHeight: 32 }]}>{value}</Text>
        {unit ? <Text style={[ui(13, 600), { color: C.textMuted, marginBottom: 4 }]}>{unit}</Text> : null}
      </Row>
      {note ? (
        <Text style={[ui(11, 500), { color: C.textDim }]} numberOfLines={2}>
          {note}
        </Text>
      ) : null}
    </View>
  );
}

export function ListRow({ icon, iconColor, title, subtitle, right, onPress, accessibilityLabel }: { icon?: IconName; iconColor?: string; title: string; subtitle?: string; right?: ReactNode; onPress?: () => void; accessibilityLabel?: string }) {
  const body = (
    <>
      {icon ? (
        <View style={[styles.rowIcon, { backgroundColor: iconColor ? `${iconColor}22` : C.surface2 }]}>
          <Icon name={icon} size={18} color={iconColor ?? C.text} />
        </View>
      ) : null}
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[ui(15, 600), { color: C.text }]} numberOfLines={2}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={[ui(13, 500), { color: C.textMuted, lineHeight: 18 }]} numberOfLines={3}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {right ?? (onPress ? <Icon name="chevron" size={18} color={C.textDim} /> : null)}
    </>
  );
  if (onPress) {
    return (
      <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel ?? title} onPress={onPress} style={({ pressed }) => [styles.listRow, pressed && styles.pressed]}>
        {body}
      </Pressable>
    );
  }
  return <View style={styles.listRow}>{body}</View>;
}

export function Segmented<T extends string>({ options, value, onChange, scroll = false }: { options: { value: T; label: string; icon?: IconName; color?: string }[]; value: T; onChange: (value: T) => void; scroll?: boolean }) {
  const scroller = useRef<ScrollView>(null);
  const offsets = useRef<Partial<Record<T, number>>>({});
  // Keep the selected tab in view, e.g. after a deep link to the last tab.
  useEffect(() => {
    const x = offsets.current[value];
    if (scroll && x != null) scroller.current?.scrollTo({ x: Math.max(0, x - 24), animated: true });
  }, [scroll, value]);
  const items = options.map((option) => {
    const active = option.value === value;
    return (
      <Pressable
        key={option.value}
        accessibilityRole="tab"
        accessibilityState={{ selected: active }}
        onPress={() => onChange(option.value)}
        onLayout={(e) => {
          offsets.current[option.value] = e.nativeEvent.layout.x;
          if (active && scroll) scroller.current?.scrollTo({ x: Math.max(0, e.nativeEvent.layout.x - 24), animated: false });
        }}
        style={({ pressed }) => [styles.segment, active && styles.segmentActive, pressed && styles.pressed, !scroll && { flex: 1 }]}
      >
        {option.icon ? <Icon name={option.icon} size={15} color={active ? C.ink : option.color ?? C.textMuted} sw={2.2} /> : null}
        <Text style={[ui(13, 700), { color: active ? C.ink : C.textMuted }]} numberOfLines={1}>
          {option.label}
        </Text>
      </Pressable>
    );
  });
  if (scroll) {
    return (
      <ScrollView ref={scroller} horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[styles.segmentWrap, { paddingRight: 6 }]}>
        {items}
      </ScrollView>
    );
  }
  return <View style={styles.segmentWrap}>{items}</View>;
}

export function EmptyState({ icon = "mountain", title, body, action }: { icon?: IconName; title: string; body?: string; action?: ReactNode }) {
  return (
    <Card tone="outline" pad={24} style={{ alignItems: "flex-start", gap: 12 }}>
      <View style={[styles.rowIcon, { width: 44, height: 44, borderRadius: 14 }]}>
        <Icon name={icon} size={22} color={C.text} />
      </View>
      <Text style={[disp(22, 800), { color: C.text }]}>{title}</Text>
      {body ? <Body muted>{body}</Body> : null}
      {action}
    </Card>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View accessibilityRole="alert" style={styles.error}>
      <Icon name="alert" size={18} color={C.serious} />
      <Text style={[ui(14, 500), { color: C.text, flex: 1, lineHeight: 20 }]}>{message}</Text>
      {onRetry ? <Button label="Retry" kind="secondary" size="sm" onPress={onRetry} /> : null}
    </View>
  );
}

export function Notice({ icon = "info", title, body, tone = "default", action }: { icon?: IconName; title: string; body?: string; tone?: "default" | "attention" | "accent"; action?: ReactNode }) {
  const color = tone === "attention" ? C.warning : tone === "accent" ? C.accent : C.textMuted;
  return (
    <View style={[styles.notice, tone === "attention" && { borderColor: "rgba(250,178,25,0.35)" }, tone === "accent" && { borderColor: C.accentLine }]}>
      <Icon name={icon} size={18} color={color} />
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={[ui(14, 700), { color: C.text }]}>{title}</Text>
        {body ? <Text style={[ui(13, 500), { color: C.textMuted, lineHeight: 19 }]}>{body}</Text> : null}
        {action}
      </View>
    </View>
  );
}

export function Skeleton({ height = 18, width = "100%", radius = 8, style }: { height?: number; width?: ViewStyle["width"]; radius?: number; style?: StyleProp<ViewStyle> }) {
  return <View accessibilityElementsHidden style={[{ height, width, borderRadius: radius, backgroundColor: C.surface2 }, style]} />;
}

export function Wordmark({ size = 15, color = C.text }: { size?: number; color?: string }) {
  return <Text style={[brand(size), { color, letterSpacing: size * 0.18 }]}>STREM</Text>;
}

const styles = StyleSheet.create({
  overline: { ...brand(10), letterSpacing: 1.6, textTransform: "uppercase" },
  page: { flex: 1, backgroundColor: C.ink },
  pageInner: { width: "100%", alignSelf: "center", gap: 20 },
  card: { borderRadius: R.lg, borderWidth: 1, overflow: "hidden" },
  pressed: { opacity: 0.8 },
  button: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 999, borderWidth: 1 },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1, alignSelf: "flex-start" },
  sectionHeader: { flexDirection: "row", alignItems: "flex-end", gap: 12 },
  stat: { flex: 1, minWidth: 120, gap: 2, padding: 14, borderRadius: R.md, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  rowIcon: { width: 36, height: 36, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: C.surface2 },
  listRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12, minHeight: 56 },
  segmentWrap: { flexDirection: "row", gap: 6, padding: 4, borderRadius: 999, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  segment: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 40, paddingHorizontal: 14, borderRadius: 999 },
  segmentActive: { backgroundColor: C.white },
  error: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: R.md, backgroundColor: "rgba(236,131,90,0.08)", borderWidth: 1, borderColor: "rgba(236,131,90,0.35)" },
  notice: { flexDirection: "row", gap: 12, padding: 14, borderRadius: R.md, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
});
