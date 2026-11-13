// Display labels. Pure formatting: nothing here decides anything clinical.

export const sexLabel = (s: string): string =>
  ({ M: 'Male', F: 'Female', O: 'Other' })[s as 'M'] ?? s;

export const typeLabel = (t: string): string =>
  ({ new: 'New visit', follow_up: 'Follow-up', emergency: 'Emergency' })[t as 'new'] ?? t;

export const fullName = (p: { first: string; last: string }): string => p.first + ' ' + p.last;

export const greetingFor = (date: Date): string => {
  const h = date.getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
};
