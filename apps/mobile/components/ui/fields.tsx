/** Form controls for the Race OS flows: inputs, choices and a calendar picker. */

import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps } from "react-native";

import { Icon, type IconName } from "@/components/ui/icon";
import { IconButton, Row } from "@/components/ui/kit";
import { C, R, disp, ui } from "@/constants/theme";

export function Input({ label, hint, error, suffix, style, ...props }: TextInputProps & { label: string; hint?: string; error?: string; suffix?: string }) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={{ gap: 6, flex: 1, minWidth: 140 }}>
      <Row>
        <Text style={[ui(13, 700), { color: C.textMuted }]}>{label}</Text>
        <View style={{ flex: 1 }} />
        {hint ? <Text style={[ui(12, 500), { color: C.textDim }]}>{hint}</Text> : null}
      </Row>
      <View style={[styles.inputWrap, focused && styles.inputFocused, error ? styles.inputError : null]}>
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={C.textDim}
          onFocus={(e) => {
            setFocused(true);
            props.onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            props.onBlur?.(e);
          }}
          style={[styles.input, props.multiline && { minHeight: 96, textAlignVertical: "top", paddingTop: 14 }, style]}
          {...props}
        />
        {suffix ? <Text style={[ui(14, 600), { color: C.textMuted, paddingRight: 16 }]}>{suffix}</Text> : null}
      </View>
      {error ? (
        <Text accessibilityRole="alert" style={[ui(12, 600), { color: C.serious }]}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

export function Choices<T extends string>({
  options,
  value,
  onChange,
  multiple,
}: {
  options: { value: T; label: string; hint?: string; icon?: IconName }[];
  value: T | T[] | null;
  onChange: (value: T) => void;
  multiple?: boolean;
}) {
  return (
    <View style={styles.choiceWrap}>
      {options.map((option) => {
        const selected = Array.isArray(value) ? value.includes(option.value) : value === option.value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole={multiple ? "checkbox" : "radio"}
            accessibilityState={multiple ? { checked: selected } : { selected }}
            onPress={() => onChange(option.value)}
            style={({ pressed }) => [styles.choice, selected && styles.choiceOn, pressed && { opacity: 0.8 }]}
          >
            {option.icon ? <Icon name={option.icon} size={16} color={selected ? C.ink : C.textMuted} /> : null}
            <View>
              <Text style={[ui(14, 700), { color: selected ? C.ink : C.text }]}>{option.label}</Text>
              {option.hint ? <Text style={[ui(11, 500), { color: selected ? "rgba(8,9,11,0.7)" : C.textMuted }]}>{option.hint}</Text> : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Scale({ label, value, onChange, low, high }: { label: string; value: number | null; onChange: (value: number) => void; low: string; high: string }) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={[ui(14, 700), { color: C.text }]}>{label}</Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        {[1, 2, 3, 4, 5].map((n) => {
          const on = value === n;
          return (
            <Pressable
              key={n}
              accessibilityRole="radio"
              accessibilityLabel={`${label} ${n} of 5`}
              accessibilityState={{ selected: on }}
              onPress={() => onChange(n)}
              style={({ pressed }) => [styles.scale, on && styles.choiceOn, pressed && { opacity: 0.8 }]}
            >
              <Text style={[disp(20, 800), { color: on ? C.ink : C.text }]}>{n}</Text>
            </Pressable>
          );
        })}
      </View>
      <Row>
        <Text style={[ui(11, 600), { color: C.textDim }]}>{low}</Text>
        <View style={{ flex: 1 }} />
        <Text style={[ui(11, 600), { color: C.textDim }]}>{high}</Text>
      </Row>
    </View>
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** A month calendar for picking a calendar date (YYYY-MM-DD, no timezone drift). */
export function DatePicker({ value, onChange, min, label }: { value: string; onChange: (iso: string) => void; min?: string; label: string }) {
  const initial = value || min || new Date().toISOString().slice(0, 10);
  const [cursor, setCursor] = useState(() => ({ y: Number(initial.slice(0, 4)), m: Number(initial.slice(5, 7)) - 1 }));
  const cells = useMemo(() => {
    const first = new Date(Date.UTC(cursor.y, cursor.m, 1));
    const offset = (first.getUTCDay() + 6) % 7;
    const days = new Date(Date.UTC(cursor.y, cursor.m + 1, 0)).getUTCDate();
    return Array.from({ length: Math.ceil((offset + days) / 7) * 7 }, (_, i) => {
      const day = i - offset + 1;
      return day >= 1 && day <= days ? `${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}` : null;
    });
  }, [cursor]);
  const move = (delta: number) =>
    setCursor((c) => {
      const m = c.m + delta;
      return { y: c.y + Math.floor(m / 12), m: ((m % 12) + 12) % 12 };
    });
  // Races are often months away: jump straight to a month instead of paging.
  const strip = useMemo(() => {
    const start = min || new Date().toISOString().slice(0, 10);
    const y0 = Number(start.slice(0, 4));
    const m0 = Number(start.slice(5, 7)) - 1;
    return Array.from({ length: 24 }, (_, i) => ({ y: y0 + Math.floor((m0 + i) / 12), m: (m0 + i) % 12 }));
  }, [min]);
  return (
    <View style={styles.calendar} accessibilityLabel={label}>
      <Row>
        <Text style={[disp(20, 800), { color: C.text, flex: 1 }]}>
          {MONTHS[cursor.m]} {cursor.y}
        </Text>
        <IconButton icon="chevronL" label="Previous month" onPress={() => move(-1)} tone="surface" size={40} />
        <IconButton icon="chevron" label="Next month" onPress={() => move(1)} tone="surface" size={40} />
      </Row>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
        {strip.map((s) => {
          const on = s.y === cursor.y && s.m === cursor.m;
          return (
            <Pressable
              key={`${s.y}-${s.m}`}
              accessibilityRole="button"
              accessibilityLabel={`${MONTHS[s.m]} ${s.y}`}
              accessibilityState={{ selected: on }}
              onPress={() => setCursor(s)}
              style={({ pressed }) => [styles.month, on && styles.monthOn, pressed && { opacity: 0.7 }]}
            >
              <Text style={[ui(12, 700), { color: on ? C.ink : C.text }]}>{MONTHS[s.m].slice(0, 3)}</Text>
              {s.m === 0 || s === strip[0] ? <Text style={[ui(10, 600), { color: on ? C.ink : C.textDim }]}>{s.y}</Text> : null}
            </Pressable>
          );
        })}
      </ScrollView>
      <View style={styles.weekHeader}>
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
          <Text key={i} style={[ui(11, 700), { color: C.textDim, flex: 1, textAlign: "center" }]}>
            {d}
          </Text>
        ))}
      </View>
      <View style={styles.grid}>
        {cells.map((iso, i) => {
          if (!iso) return <View key={i} style={styles.cell} />;
          const disabled = Boolean(min && iso < min);
          const on = iso === value;
          return (
            <Pressable
              key={i}
              accessibilityRole="button"
              accessibilityLabel={iso}
              accessibilityState={{ selected: on, disabled }}
              disabled={disabled}
              onPress={() => onChange(iso)}
              style={({ pressed }) => [styles.cell, on && styles.cellOn, pressed && { opacity: 0.7 }]}
            >
              <Text style={[ui(14, on ? 800 : 600), { color: disabled ? C.textDim : on ? C.ink : C.text, opacity: disabled ? 0.5 : 1 }]}>{Number(iso.slice(8))}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  inputWrap: { flexDirection: "row", alignItems: "center", minHeight: 52, borderRadius: R.md, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  inputFocused: { borderColor: C.text },
  inputError: { borderColor: C.serious },
  // minWidth 0: a browser <input> won't shrink below its intrinsic width beside a unit otherwise.
  // No browser outline: the field's border already turns white on focus.
  input: { flex: 1, minWidth: 0, minHeight: 50, paddingHorizontal: 16, color: C.text, outlineStyle: "solid", outlineWidth: 0, ...ui(16, 500) },
  choiceWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  choice: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 14, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  choiceOn: { backgroundColor: C.white, borderColor: C.white },
  scale: { flex: 1, height: 48, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  calendar: { gap: 10, padding: 14, borderRadius: R.lg, backgroundColor: C.surface, borderWidth: 1, borderColor: C.line },
  weekHeader: { flexDirection: "row" },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: { width: `${100 / 7}%`, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 12 },
  cellOn: { backgroundColor: C.white },
  month: { minWidth: 52, height: 44, paddingHorizontal: 10, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: C.surface2, borderWidth: 1, borderColor: C.line },
  monthOn: { backgroundColor: C.white, borderColor: C.white },
});
