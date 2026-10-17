import { useState } from "react";
import { MotionConfig, motion } from "motion/react";
import Painted from "./scene/Painted";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import Calendar from "./components/Calendar";
import Notes from "./components/Notes";
import Footer from "./components/Footer";
import { LoadError, LoadingSkeleton } from "./components/States";
import { RoutineChooser, RoutineSwitch } from "./components/RoutineMode";
import { DAY_NAME } from "./components/calendar/geometry";
import { TEMPLATE_DAY, usePlanner } from "./lib/usePlanner";
import { WEEKDAYS, type RoutineMode, type View, type Weekday } from "./lib/types";

const todayKey = (): Weekday => WEEKDAYS[(new Date().getDay() + 6) % 7];
const rise = (i: number) => ({
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { type: "spring" as const, stiffness: 120, damping: 20, delay: i * 0.08 },
});

export default function App() {
  const p = usePlanner();
  const [view, setView] = useState<View>(() => (window.innerWidth < 768 ? "day" : "week"));
  const [day, setDay] = useState<Weekday>(todayKey);
  const oneDay = p.routineMode === "day";
  const shownView: View = oneDay ? "day" : view;
  const shownDay: Weekday = oneDay ? TEMPLATE_DAY : day;

  const switchMode = (mode: RoutineMode) => {
    if (mode === "day") {
      const same = (d: Weekday) => JSON.stringify(p.week[d].map(({ id: _, ...b }) => b));
      const differs = WEEKDAYS.some((d) => same(d) !== same(day));
      if (differs && !window.confirm(`Use ${DAY_NAME[day]} as your typical day? It replaces what the other days have.`)) return;
    }
    p.chooseRoutineMode(mode, day);
  };

  return (
    <MotionConfig reducedMotion="user">
      <Painted />
      <div className="relative mx-auto flex min-h-[100dvh] max-w-[1400px] flex-col gap-5 px-4 py-5 md:px-8 md:py-8">
        <motion.div {...rise(0)} className="relative z-50">
          <Header
            view={shownView}
            onViewChange={setView}
            oneDay={oneDay}
            saveStatus={p.saveStatus}
            saveError={p.saveError}
            onRetry={p.retrySave}
            categories={p.categories}
            onImport={p.importBlocks}
            onCategories={p.updateCategories}
            day={shownDay}
            week={p.week}
            notes={p.notes}
          />
        </motion.div>

        {p.load === "loading" && <LoadingSkeleton />}
        {p.load === "error" && <LoadError message={p.loadError} onRetry={p.reload} />}
        {p.load === "ready" && (
          <main className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-[20rem_1fr]">
            <motion.div {...rise(1)} className="order-2 min-w-0 lg:order-none">
              <Sidebar
                categories={p.categories}
                week={p.week}
                defaults={p.defaults}
                onChange={p.updateCategories}
                onRemove={p.removeCategory}
                calendars={p.appCalendars}
                oneDay={oneDay}
              />
            </motion.div>
            <motion.div {...rise(2)} className="flex min-w-0 flex-col gap-5">
              {p.routineMode && <RoutineSwitch mode={p.routineMode} onChange={switchMode} />}
              <Calendar
                view={shownView}
                single={oneDay}
                week={p.week}
                categories={p.categories}
                day={shownDay}
                onDayChange={setDay}
                onChange={p.updateWeek}
                dayStart={p.dayStart}
              />
              <Notes notes={p.notes} onChange={p.updateNotes} freeTime={p.freeTime} onFreeTime={p.updateFreeTime} />
            </motion.div>
          </main>
        )}

        {p.load === "ready" && p.routineMode === null && <RoutineChooser onChoose={(m) => p.chooseRoutineMode(m)} />}
        <Footer />
      </div>
    </MotionConfig>
  );
}
